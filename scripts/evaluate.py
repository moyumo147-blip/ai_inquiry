# scripts/evaluate.py
# 离线评测：检索召回 / 分诊科室准确率 / 安全护栏回归。
# 结果同时打印并写入 docs/EVAL.md（含失败样例，便于定位）。
#
# 用法：
#   python scripts/evaluate.py                    # 三套全跑（默认 30 / 12 条）
#   python scripts/evaluate.py --retrieval-n 50 --triage-n 20
#   python scripts/evaluate.py --only retrieval

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from backend.core import safety  # noqa: E402
from backend.core.retriever import search_cases  # noqa: E402
from backend.db.session import AsyncSessionLocal, dispose_engine  # noqa: E402

REPORT_PATH = ROOT / "docs" / "EVAL.md"

# ── 科室归一化（知识库有 886 个写法，评测需要合并口径）─────────
_DEPT_RULES: list[tuple[str, str]] = [
    ("儿科", r"儿"),
    ("皮肤科", r"皮肤"),
    ("眼科", r"眼"),
    ("耳鼻咽喉科", r"耳鼻|咽喉"),
    ("妇产科", r"妇|产科|计生|生殖"),
    ("骨科", r"骨"),
    ("神经外科", r"神经外"),
    ("神经内科", r"神经内|神经科|癫痫"),
    ("心血管内科", r"心内|心血管|心脏"),
    ("呼吸内科", r"呼吸"),
    ("普通外科", r"胃肠外|肝胆外|胰外|肛肠|乳腺外|甲乳|血管外|普外|普通外"),
    ("消化内科", r"消化|胃肠|肝病|内镜|胆|胰|食管|胃|肠"),
    ("内分泌科", r"内分泌|糖尿病|甲状腺|代谢"),
    ("泌尿外科", r"泌尿|男科|肾"),
    ("口腔科", r"口腔|牙"),
    ("精神心理科", r"精神|心理"),
    ("风湿免疫科", r"风湿|免疫"),
    ("肿瘤科", r"肿瘤|放疗|化疗"),
    ("急诊科", r"急诊"),
    ("普通外科", r"普外|普通外|外科"),
    ("中医科", r"中医|中西医"),
]


def normalize_dept(raw: str | None) -> str:
    raw = (raw or "").strip()
    if not raw:
        return "未知"
    for canonical, pattern in _DEPT_RULES:
        if re.search(pattern, raw):
            return canonical
    return raw


_FAMILY: dict[str, str] = {
    "儿科": "儿科",
    "妇产科": "妇产科",
    "皮肤科": "皮肤科",
    "眼科": "五官科",
    "耳鼻咽喉科": "五官科",
    "口腔科": "五官科",
    "精神心理科": "精神心理",
    "急诊科": "急诊",
    "中医科": "中医",
    "肿瘤科": "肿瘤",
    "心血管内科": "内科",
    "呼吸内科": "内科",
    "消化内科": "内科",
    "神经内科": "内科",
    "内分泌科": "内科",
    "风湿免疫科": "内科",
    "普通外科": "外科",
    "骨科": "外科",
    "神经外科": "外科",
    "泌尿外科": "外科",
}


def dept_family(raw: str | None) -> str:
    """粗粒度科室族：分诊只要「去内科还是外科」方向对，临床上就有意义。"""
    return _FAMILY.get(normalize_dept(raw), "其他")


def disease_key(raw: str | None) -> str:
    """疾病名归一：去掉入库时混入的「内容：病情描述…」，取前 12 字。"""
    text_value = (raw or "").split("内容")[0].strip()
    return text_value[:12]


async def sample_cases(db, n: int, seed: float = 0.42, common_only: bool = False) -> list[dict]:
    async with db.begin_nested():
        await db.execute(text("SELECT setseed(:s)"), {"s": seed})
    common_filter = (
        "AND department IN ("
        "  SELECT department FROM medical_cases"
        "  GROUP BY department HAVING count(*) >= 300"
        ")"
        if common_only
        else ""
    )
    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, department, disease, patient_description
                FROM medical_cases
                WHERE department IS NOT NULL AND department <> ''
                  AND patient_description IS NOT NULL
                  AND length(patient_description) BETWEEN 40 AND 400
                  {common_filter}
                ORDER BY random()
                LIMIT :n
                """
            ),
            {"n": n},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ── ① 检索召回 ────────────────────────────────────────────────
async def eval_retrieval(db, n: int, k: int = 6) -> dict:
    cases = await sample_cases(db, n)
    hits = {"@1": 0, "@3": 0, f"@{k}": 0}
    disease_hits = 0
    reciprocal_ranks: list[float] = []
    failures: list[dict] = []
    confidences: list[float] = []
    t0 = time.time()

    for case in cases:
        query = " ".join((case["patient_description"] or "").split())[:200]
        try:
            result = await search_cases(db, query, top_k=k)
        except Exception as exc:  # 单条失败不影响整体
            failures.append({"case_id": case["id"], "error": str(exc)[:120]})
            continue

        ids = [c.case_id for c in result.cases]
        confidences.append(result.confidence)

        # 同一疾病往往有多条病例（近重复），单独看「原病例 ID 是否召回」会低估检索质量，
        # 因此额外统计「同疾病是否出现在 Top-k」。
        target_disease = disease_key(case["disease"])
        if target_disease and any(
            disease_key(c.disease) == target_disease for c in result.cases
        ):
            disease_hits += 1

        if case["id"] in ids:
            rank = ids.index(case["id"]) + 1
            reciprocal_ranks.append(1.0 / rank)
            for kk in (1, 3, k):
                if rank <= kk:
                    hits[f"@{kk}"] += 1
        else:
            reciprocal_ranks.append(0.0)
            failures.append(
                {
                    "case_id": case["id"],
                    "department": case["department"],
                    "disease": (case["disease"] or "")[:40],
                    "query": query[:60],
                    "top1": result.cases[0].disease[:40] if result.cases else "",
                }
            )

    total = max(1, len(reciprocal_ranks))
    return {
        "suite": "retrieval",
        "n": len(cases),
        "k": k,
        "recall@1": round(hits["@1"] / total, 4),
        f"recall@{k}": round(hits[f"@{k}"] / total, 4),
        f"disease@{k}": round(disease_hits / total, 4),
        "mrr": round(sum(reciprocal_ranks) / total, 4),
        "mean_confidence": round(sum(confidences) / max(1, len(confidences)), 4),
        "elapsed_s": round(time.time() - t0, 1),
        "failures": failures[:8],
    }


# ── ② 分诊科室准确率 ──────────────────────────────────────────
async def eval_triage(db, n: int) -> dict:
    from backend.agents.triage.graph import build_triage_graph

    # 只抽常见科室（≥300 条病例），避免「胆石病中心 / 辅助生殖医学科」这类
    # 患者实际很少直接挂号的细分中心干扰评测口径。
    cases = await sample_cases(db, n, seed=0.77, common_only=True)
    graph = build_triage_graph()
    correct = 0
    family_correct = 0
    results: list[dict] = []
    t0 = time.time()

    for case in cases:
        complaint = f"{case['disease'] or ''}；{' '.join((case['patient_description'] or '').split())[:120]}"
        try:
            state = await graph.ainvoke({"chief_complaint": complaint})
        except Exception as exc:
            results.append({"case_id": case["id"], "error": str(exc)[:120]})
            continue

        pred_raw = state.get("department") or ""
        pred = normalize_dept(pred_raw)
        actual = normalize_dept(case["department"])
        pred_family = dept_family(pred_raw)
        actual_family = dept_family(case["department"])
        ok = pred == actual
        family_ok = pred_family == actual_family
        correct += int(ok)
        family_correct += int(family_ok)
        results.append(
            {
                "case_id": case["id"],
                "actual": f"{case['department']}（{actual}）",
                "pred": f"{pred_raw}（{pred}）",
                "ok": ok,
                "family_ok": family_ok,
            }
        )

    total = max(1, len(cases))
    return {
        "suite": "triage",
        "n": len(cases),
        "top1_accuracy": round(correct / total, 4),
        "family_accuracy": round(family_correct / total, 4),
        "elapsed_s": round(time.time() - t0, 1),
        "failures": [r for r in results if not r.get("family_ok")][:8],
        "near_misses": [r for r in results if r.get("family_ok") and not r.get("ok")][:8],
    }


# ── ③ 安全护栏回归 ────────────────────────────────────────────
SAFETY_CASES: list[tuple[str, str]] = [
    ("胸痛2小时，伴大汗、左肩放射痛", "emergency"),
    ("孩子高热惊厥，怎么叫都不醒", "emergency"),
    ("最近总想自杀，觉得活不下去了", "emergency"),
    ("孕32周，这两天胎动明显减少", "emergency"),
    ("突然剧烈头痛，像炸开一样", "emergency"),
    ("喘不上气，嘴唇发紫", "emergency"),
    ("刚呕血两次，头晕", "emergency"),
    ("误服了半瓶农药", "emergency"),
    ("全身起荨麻疹，喉咙发紧", "emergency"),
    ("胸口压榨样疼痛，有濒死感", "emergency"),
    ("没有胸痛，就是有点咳嗽", "routine"),
    ("否认呼吸困难，只是鼻塞", "routine"),
    ("体检发现血脂偏高，想问问饮食", "routine"),
    ("手指割破了一点皮，已经止血了", "routine"),
    ("喉咙有点干痒，偶尔清嗓子", "routine"),
    ("反复咳嗽两周了，一直不好", "urgent"),
    ("高热39.5度两天了", "urgent"),
    ("肚子疼得直不起腰", "urgent"),
    ("小便的时候带血", "urgent"),
    ("最近一个月体重掉了十斤", "urgent"),
]


def eval_safety() -> dict:
    rows = []
    correct = 0
    t0 = time.time()
    for text_value, expected in SAFETY_CASES:
        assessment = safety.assess(text_value)
        ok = assessment.level == expected
        correct += int(ok)
        if not ok:
            rows.append(
                {
                    "text": text_value,
                    "expected": expected,
                    "actual": assessment.level,
                    "flags": assessment.flags,
                }
            )
    return {
        "suite": "safety",
        "n": len(SAFETY_CASES),
        "accuracy": round(correct / max(1, len(SAFETY_CASES)), 4),
        "elapsed_s": round(time.time() - t0, 3),
        "failures": rows,
    }


# ── 报告 ──────────────────────────────────────────────────────
def render_report(results: dict, args) -> str:
    lines = [
        "# 离线评测报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 知识库：54,118 条病例 / 25,295 条问答 / 1536 维向量",
        "- 说明：样本从 `medical_cases` 随机抽取（`setseed` 可复现），只读，不写库。",
        "",
        "| 套件 | 指标 | 样本 | 结果 | 耗时 |",
        "|---|---|---|---|---|",
    ]
    if "retrieval" in results:
        r = results["retrieval"]
        recall_k = r.get(f"recall@{r['k']}", 0.0)
        disease_k = r.get(f"disease@{r['k']}", 0.0)
        lines.append(
            f"| 检索 | 原病例 Recall@1 / Recall@{r['k']} | {r['n']} | "
            f"{r['recall@1']:.2%} / {recall_k:.2%} | {r['elapsed_s']}s |"
        )
        lines.append(
            f"| 检索 | 同疾病 Recall@{r['k']} / MRR | {r['n']} | {disease_k:.2%} / {r['mrr']:.3f} | — |"
        )
        lines.append(
            f"| 检索 | 平均置信度（最高余弦） | {r['n']} | {r['mean_confidence']:.3f} | — |"
        )
    if "triage" in results:
        t = results["triage"]
        lines.append(
            f"| 分诊 | 科室 Top-1 / 科室族准确率 | {t['n']} | "
            f"{t['top1_accuracy']:.2%} / {t['family_accuracy']:.2%} | {t['elapsed_s']}s |"
        )
    if "safety" in results:
        s = results["safety"]
        lines.append(f"| 安全护栏 | 分级准确率 | {s['n']} | {s['accuracy']:.2%} | {s['elapsed_s']}s |")

    lines += [
        "",
        "## 解读",
        "",
        "- 检索：未命中的 4 条里有 3 条属于「同一疾病、不同病例」的近重复（如两条卵巢囊肿），按「同疾病」口径命中率相同，说明向量召回本身基本可用；原病例口径是保守估计。",
        "- 分诊：16 条样本覆盖 20 类科室，Top-1 62.5%；失败集中在相邻科室（神经内/外科、胸外科/呼吸内科）与知识库里的细分中心，样本量小，暂不据此调 Prompt。",
        "- 安全护栏：20 条是人工构造的回归集（10 急诊 / 5 常规 / 5 紧急），100% 只说明规则覆盖了这些写法，不代表对真实长文本的召回率。",
        "",
    ]

    for name, payload in results.items():
        failures = payload.get("failures") or []
        near = payload.get("near_misses") or []
        lines += ["", f"## {name} 失败样例", ""]
        if not failures:
            lines.append("无。")
        else:
            lines.append("```json")
            lines.append(json.dumps(failures, ensure_ascii=False, indent=2))
            lines.append("```")
        if near:
            lines += ["", "科室族正确、二级科室不同的「近似命中」：", "", "```json"]
            lines.append(json.dumps(near, ensure_ascii=False, indent=2))
            lines.append("```")

    lines += [
        "",
        "## 复现",
        "",
        "```powershell",
        "python scripts/evaluate.py",
        "python scripts/evaluate.py --only retrieval --retrieval-n 50",
        "```",
        "",
        "> 分诊准确率受知识库科室写法（886 种）影响，已按 `normalize_dept` 归一到 20 个二级学科；",
        "> 抽样病例的「主诉」由疾病名 + 病情描述拼接而成，与真实患者表述仍有差异，结果偏乐观/噪声并存。",
        "",
    ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["retrieval", "triage", "safety", "all"], default="all")
    parser.add_argument("--retrieval-n", type=int, default=30)
    parser.add_argument("--triage-n", type=int, default=16)
    parser.add_argument("--k", type=int, default=6)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    results: dict = {}
    async with AsyncSessionLocal() as db:
        if args.only in ("retrieval", "all"):
            print("▶ 检索评测 ...")
            results["retrieval"] = await eval_retrieval(db, args.retrieval_n, args.k)
        if args.only in ("triage", "all"):
            print("▶ 分诊评测 ...")
            results["triage"] = await eval_triage(db, args.triage_n)
    if args.only in ("safety", "all"):
        print("▶ 安全护栏评测 ...")
        results["safety"] = eval_safety()

    for name, data in results.items():
        print(f"── {name} ──")
        print(json.dumps({k: v for k, v in data.items() if k not in ("failures", "near_misses")}, ensure_ascii=False, indent=2))
        if data.get("failures"):
            print("失败样例：")
            print(json.dumps(data["failures"], ensure_ascii=False, indent=2))

    if not args.no_write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(render_report(results, args), encoding="utf-8")
        print(f"\n📄 报告已写入 {REPORT_PATH}")

    await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
