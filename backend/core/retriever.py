# backend/core/retriever.py
# 医疗知识库检索：pgvector 向量召回 → 规则精排（科室/关键词加权）→ 病例 + 相似问答。
# 对应 EduAgent 的 core/knowledge_base.py + core/reranker.py 两个模块的职责。

from dataclasses import dataclass, field

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.core.embeddings import embed_query, vector_literal
from backend.core.exceptions import RetrievalError
from backend.core.logger import get_logger

logger = get_logger(__name__)

_STOPWORDS = set("的了是我有和就不人都一个上也很到说要去你会着没有看好这那么什么怎么怎样如何可以可能吗呢啊吧呀")


@dataclass
class RetrievedCase:
    case_id: int
    score: float              # 精排后的综合分
    similarity: float         # 原始余弦相似度
    hospital: str
    department: str
    disease: str
    patient_description: str
    help_wanted: str
    source_url: str
    chunk_text: str
    qa_pairs: list[dict] = field(default_factory=list)

    def snippet(self, limit: int = 140) -> str:
        parts = [p for p in (self.patient_description, self.help_wanted) if p]
        raw = " ".join(parts) or self.chunk_text
        raw = " ".join(raw.split())
        return raw if len(raw) <= limit else raw[:limit] + "…"

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "score": round(self.score, 4),
            "similarity": round(self.similarity, 4),
            "hospital": self.hospital,
            "department": self.department,
            "disease": self.disease,
            "snippet": self.snippet(),
            "help_wanted": (self.help_wanted or "")[:200],
            "source_url": self.source_url,
            "qa_pairs": self.qa_pairs,
        }


@dataclass
class RetrievalResult:
    query: str
    cases: list[RetrievedCase] = field(default_factory=list)
    confidence: float = 0.0          # 最高余弦相似度
    coverage: str = "none"           # none / weak / good

    @property
    def is_confident(self) -> bool:
        return self.confidence >= get_settings().min_confidence

    def to_context(self, max_chars: int = 6000) -> str:
        """拼成 Prompt 里的【参考病例】段落。"""
        if not self.cases:
            return "（知识库未检索到相关病例）"
        blocks: list[str] = []
        used = 0
        for i, c in enumerate(self.cases, 1):
            block = (
                f"[病例{i}] 医院：{c.hospital or '未知'}｜科室：{c.department or '未知'}｜"
                f"疾病：{c.disease or '未知'}\n"
                f"患者情况：{c.snippet(220)}\n"
                f"患者诉求：{(c.help_wanted or '未提供')[:160]}"
            )
            if c.qa_pairs:
                qa = c.qa_pairs[0]
                block += f"\n医生回答节选：{qa.get('answer', '')[:180]}"
            if used + len(block) > max_chars:
                break
            blocks.append(block)
            used += len(block)
        return "\n\n".join(blocks)

    def to_sources(self) -> list[dict]:
        return [c.to_dict() for c in self.cases]


def _ngrams(text_value: str, n: int = 2) -> set[str]:
    """极简中文关键词切分：汉字/字母数字序列的 n-gram，用于规则精排。"""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text_value)
    grams: set[str] = set()
    for token in cleaned.split():
        for i in range(len(token) - n + 1):
            gram = token[i : i + n]
            if gram not in _STOPWORDS:
                grams.add(gram)
    return grams


def _keyword_overlap(query: str, haystack: str) -> float:
    q = _ngrams(query)
    if not q:
        return 0.0
    h = _ngrams(haystack)
    hit = len(q & h)
    return min(1.0, hit / max(1, min(len(q), 12)))


async def search_cases(
    db: AsyncSession,
    query: str,
    *,
    top_k: int | None = None,
    department: str | None = None,
) -> RetrievalResult:
    """向量召回 + 精排，返回带病例元信息的结果。"""
    settings = get_settings()
    top_k = top_k or settings.retrieval_top_k
    candidates = settings.retrieval_candidates

    if not query.strip():
        raise RetrievalError("检索问题为空")

    vector = await embed_query(query)
    vec_literal = vector_literal(vector)

    dept_filter = "AND m.department ILIKE :dept" if department else ""
    sql = text(
        f"""
        SELECT m.id            AS case_id,
               m.hospital      AS hospital,
               m.department    AS department,
               m.disease       AS disease,
               COALESCE(m.patient_description, '') AS patient_description,
               COALESCE(m.help_wanted, '')         AS help_wanted,
               COALESCE(m.source_url, '')          AS source_url,
               c.chunk_text    AS chunk_text,
               1 - (c.embedding <=> CAST(:vec AS vector)) AS score
        FROM case_chunks c
        JOIN medical_cases m ON m.id = c.case_id
        WHERE c.embedding IS NOT NULL
        {dept_filter}
        ORDER BY c.embedding <=> CAST(:vec AS vector)
        LIMIT :limit
        """
    )
    params = {"vec": vec_literal, "limit": candidates}
    if department:
        params["dept"] = f"%{department}%"

    rows = (await db.execute(sql, params)).mappings().all()
    if not rows:
        return RetrievalResult(query=query, confidence=0.0, coverage="none")

    # ── 规则精排：余弦相似度为主，科室命中与关键词重合加权 ──
    scored: list[tuple[float, dict]] = []
    for row in rows:
        sim = float(row["score"] or 0.0)
        dept_match = 1.0 if department and department in (row["department"] or "") else 0.0
        haystack = f"{row['disease']} {row['patient_description']} {row['help_wanted']}"
        overlap = _keyword_overlap(query, haystack)
        final = 0.75 * sim + 0.15 * dept_match + 0.10 * overlap
        scored.append((final, dict(row)))

    scored.sort(key=lambda item: item[0], reverse=True)

    # ── 同一病例只保留分数最高的 chunk ──
    seen: set[int] = set()
    cases: list[RetrievedCase] = []
    for final, row in scored:
        if row["case_id"] in seen:
            continue
        seen.add(row["case_id"])
        cases.append(
            RetrievedCase(
                case_id=row["case_id"],
                score=final,
                similarity=float(row["score"] or 0.0),
                hospital=row["hospital"] or "",
                department=row["department"] or "",
                disease=row["disease"] or "",
                patient_description=row["patient_description"] or "",
                help_wanted=row["help_wanted"] or "",
                source_url=row["source_url"] or "",
                chunk_text=row["chunk_text"] or "",
            )
        )
        if len(cases) >= top_k:
            break

    confidence = max((c.similarity for c in cases), default=0.0)
    coverage = (
        "good" if confidence >= settings.min_confidence else ("weak" if confidence > 0.15 else "none")
    )

    await _attach_qa(db, cases)

    logger.info(
        "retriever.search_done",
        query_chars=len(query),
        candidates=len(rows),
        top_k=len(cases),
        confidence=round(confidence, 3),
        coverage=coverage,
    )
    return RetrievalResult(query=query, cases=cases, confidence=confidence, coverage=coverage)


async def _attach_qa(db: AsyncSession, cases: list[RetrievedCase], per_case: int = 2) -> None:
    """给命中的病例补 1-2 条真实医患问答（qa_pairs 未做向量化，按 case_id 关联即可）。"""
    if not cases:
        return
    sql = text(
        """
        SELECT case_id, turn_no, patient_question, doctor_answer
        FROM qa_pairs
        WHERE case_id IN :ids AND doctor_answer IS NOT NULL AND doctor_answer <> ''
        ORDER BY case_id, turn_no
        """
    ).bindparams(bindparam("ids", expanding=True))

    rows = (await db.execute(sql, {"ids": [c.case_id for c in cases]})).mappings().all()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        bucket = grouped.setdefault(row["case_id"], [])
        if len(bucket) < per_case:
            bucket.append(
                {
                    "question": row["patient_question"] or "",
                    "answer": row["doctor_answer"] or "",
                    "turn_no": row["turn_no"],
                }
            )
    for case in cases:
        case.qa_pairs = grouped.get(case.case_id, [])


async def get_case_detail(db: AsyncSession, case_id: int) -> dict | None:
    sql = text(
        """
        SELECT id, hospital, department, disease, patient_description, help_wanted,
               treatment_history, dialogue, source_url, created_at
        FROM medical_cases WHERE id = :cid
        """
    )
    row = (await db.execute(sql, {"cid": case_id})).mappings().first()
    if not row:
        return None
    qa_sql = text(
        """
        SELECT turn_no, patient_question, doctor_answer
        FROM qa_pairs WHERE case_id = :cid ORDER BY turn_no
        """
    )
    qa_rows = (await db.execute(qa_sql, {"cid": case_id})).mappings().all()
    data = dict(row)
    data["qa_pairs"] = [dict(r) for r in qa_rows]
    return data


async def search_cases_by_keyword(
    db: AsyncSession,
    keyword: str = "",
    department: str = "",
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[dict], int]:
    """病例库关键词检索（供前端「知识库浏览」页使用）。"""
    like = f"%{keyword}%"
    where = ["1 = 1"]
    params: dict = {}
    if keyword:
        where.append(
            "(disease ILIKE :like OR patient_description ILIKE :like OR hospital ILIKE :like)"
        )
        params["like"] = like
    if department:
        where.append("department = :dept")
        params["dept"] = department
    where_sql = " AND ".join(where)
    offset = max(0, (page - 1) * page_size)

    total = (
        await db.execute(text(f"SELECT count(*) FROM medical_cases WHERE {where_sql}"), params)
    ).scalar_one()

    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, hospital, department, disease,
                       COALESCE(patient_description,'') AS patient_description,
                       COALESCE(help_wanted,'') AS help_wanted
                FROM medical_cases
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": page_size, "offset": offset},
        )
    ).mappings().all()

    items = []
    for row in rows:
        desc = " ".join((row["patient_description"] or "").split())
        items.append(
            {
                "case_id": row["id"],
                "hospital": row["hospital"],
                "department": row["department"],
                "disease": row["disease"],
                "snippet": desc[:160] + ("…" if len(desc) > 160 else ""),
                "help_wanted": (row["help_wanted"] or "")[:120],
            }
        )
    return items, int(total)


async def list_departments(db: AsyncSession, limit: int = 40) -> list[dict]:
    rows = (
        await db.execute(
            text(
                """
                SELECT department, count(*) AS cnt
                FROM medical_cases
                WHERE department IS NOT NULL AND department <> ''
                GROUP BY department
                ORDER BY cnt DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [{"department": r["department"], "count": int(r["cnt"])} for r in rows]


async def knowledge_stats(db: AsyncSession) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT (SELECT count(*) FROM medical_cases)       AS cases,
                       (SELECT count(*) FROM qa_pairs)            AS qa_pairs,
                       (SELECT count(*) FROM case_chunks)         AS chunks,
                       (SELECT count(DISTINCT department) FROM medical_cases) AS departments
                """
            )
        )
    ).mappings().one()
    return {k: int(v) for k, v in row.items()}
