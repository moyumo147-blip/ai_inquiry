# backend/agents/consultation/nodes.py
# 问诊 Agent 的节点实现：
#   safety_check（规则）→ classify（路由）→ retrieve（pgvector）→ generate（流式生成）→ suggest_followup（追问）

import re
from functools import partial

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.consultation.prompts import (
    CHITCHAT_SYSTEM_PROMPT,
    CONSULT_SYSTEM_PROMPT,
    CONSULT_USER_TEMPLATE,
    FOLLOWUP_SYSTEM_PROMPT,
    FOLLOWUP_USER_TEMPLATE,
)
from backend.agents.consultation.state import ConsultationState
from backend.config import get_settings
from backend.core import safety
from backend.core.exceptions import RetrievalError
from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.core.retriever import search_cases

logger = get_logger(__name__)

_RECORD_RE = re.compile(r"((生成|写|整理|导出|保存).{0,6}病历)|(病历.{0,4}(生成|整理))")
_CHITCHAT_RE = re.compile(
    r"^(你好|您好|hi|hello|在吗|在么|谢谢|多谢|再见|早安|晚安|好的|嗯嗯)[\s!！。.~，,]*$",
    re.IGNORECASE,
)

RECORD_HINT = (
    "需要我把这次问诊整理成一份结构化病历吗？\n\n"
    "点击右上角的「生成病历」按钮，我会基于本次对话生成包含"
    "**主诉 / 现病史 / 既往史 / 初步评估 / 诊疗计划**的 SOAP 病历，"
    "你可以直接修改后保存或打印。"
)


def _msg_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", ""))
            else:
                parts.append(str(part))
        return "".join(parts)
    return str(content)


def _history_text(history: list[dict], limit: int = 8, max_chars: int = 300) -> str:
    if not history:
        return "（这是本次问诊的第一条消息）"
    lines = []
    for item in history[-limit:]:
        role = "患者" if item.get("role") == "user" else "助手"
        text = " ".join((item.get("content") or "").split())[:max_chars]
        lines.append(f"{role}：{text}")
    return "\n".join(lines)


async def safety_check_node(state: ConsultationState) -> dict:
    """红旗症状扫描：把最近两条用户消息一起看，避免上下文断裂。"""
    history = state.get("history") or []
    recent_user = " ".join(
        " ".join((m.get("content") or "").split())[:300]
        for m in history
        if m.get("role") == "user"
    )
    text = f"{state.get('session_complaint') or ''} {recent_user} {state.get('query', '')}"
    assessment = safety.assess(text)

    # 会话已被分诊为急诊：后续轮次保持急诊口径，避免患者追问时被降级
    if state.get("session_urgency") == "emergency" and assessment.level != "emergency":
        assessment.level = "emergency"
        assessment.advice = safety.EMERGENCY_ADVICE
        if "既往分诊为急诊" not in assessment.flags:
            assessment.flags.append("既往分诊为急诊")

    logger.info(
        "consultation.safety",
        level=assessment.level,
        flags=assessment.flags,
        session_id=state.get("session_id"),
    )
    return {"safety": assessment.to_dict(), "urgency": assessment.level}


async def classify_node(state: ConsultationState) -> dict:
    query = (state.get("query") or "").strip()
    if _RECORD_RE.search(query):
        return {"intent": "record"}
    if _CHITCHAT_RE.match(query):
        return {"intent": "chitchat"}
    return {"intent": "medical"}


async def retrieve_node(state: ConsultationState, db: AsyncSession) -> dict:
    if not state.get("enable_retrieval", True):
        return {
            "context": "（本次未启用知识库检索）",
            "citations": [],
            "confidence": 0.0,
            "coverage": "none",
        }
    # 追问往往很短（"需要做哪些检查？"），单独检索会跑偏；
    # 把会话主诉拼进查询，保证检索始终围绕本次病情。
    parts = [state.get("session_complaint") or "", state.get("query") or ""]
    search_query = "；".join(p.strip() for p in parts if p.strip())[:300] or state["query"]

    try:
        result = await search_cases(db, search_query, department=state.get("department"))
    except RetrievalError as exc:
        logger.error("consultation.retrieve_failed", error=str(exc))
        return {
            "context": "（知识库暂时不可用）",
            "citations": [],
            "confidence": 0.0,
            "coverage": "none",
        }
    return {
        "context": result.to_context(),
        "citations": result.to_sources(),
        "confidence": result.confidence,
        "coverage": result.coverage,
    }


async def generate_node(state: ConsultationState) -> dict:
    """生成回答。medical 走 RAG，chitchat 走轻量对话，record 走固定引导。"""
    intent = state.get("intent", "medical")
    safety_info = state.get("safety") or {}
    settings = get_settings()

    if intent == "record":
        return {"answer": RECORD_HINT, "answer_mode": "record_hint"}

    if intent == "chitchat":
        llm = get_llm("consultation", temperature=0.6, streaming=True)
        resp = await llm.ainvoke(
            [
                SystemMessage(content=CHITCHAT_SYSTEM_PROMPT),
                HumanMessage(content=state.get("query", "")),
            ]
        )
        return {"answer": _msg_text(resp).strip(), "answer_mode": "chitchat"}

    prompt = CONSULT_USER_TEMPLATE.format(
        age=state.get("age") if state.get("age") is not None else "未知",
        gender=state.get("gender") or "未知",
        department=state.get("department") or "未指定",
        summary=state.get("summary") or "（无，这是本次问诊的开始）",
        history=_history_text(state.get("history") or []),
        context=state.get("context") or "（无）",
        safety=(
            f"级别={safety_info.get('level')}；红旗症状="
            f"{'、'.join(safety_info.get('flags') or []) or '无'}；"
            f"建议级别={safety_info.get('advice', '')[:40]}"
        ),
        query=state.get("query", ""),
    )

    llm = get_llm("consultation", streaming=True)
    try:
        resp = await llm.ainvoke(
            [SystemMessage(content=CONSULT_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        answer = _msg_text(resp).strip()
    except Exception as exc:
        logger.error("consultation.generate_failed", error=str(exc)[:300])
        return {
            "answer": "抱歉，AI 服务暂时不可用，请稍后重试。若症状较重，请直接前往医院就诊。",
            "answer_mode": "llm_direct",
            "error": str(exc)[:200],
        }

    if safety_info.get("level") != "routine":
        answer = f"{answer}\n\n> {safety_info.get('advice', '')}".strip()

    answer_mode = "rag" if (state.get("confidence") or 0) >= settings.min_confidence else "llm_direct"
    return {"answer": answer, "answer_mode": answer_mode, "disclaimer": safety.DISCLAIMER}


async def suggest_followup_node(state: ConsultationState) -> dict:
    """生成 ≤3 个追问。急诊 / 寒暄 / 病历场景不需要。"""
    if state.get("intent") != "medical" or state.get("urgency") == "emergency":
        return {"followups": []}

    missing = []
    if state.get("coverage") == "weak":
        missing.append("知识库匹配较弱，需要更具体的症状描述")

    prompt = FOLLOWUP_USER_TEMPLATE.format(
        history=_history_text(state.get("history") or []),
        answer=(state.get("answer") or "")[:600],
        missing="、".join(missing) or "无明显缺失（按常规问诊补全）",
    )
    prompt += "\n\n请直接输出问题，每行一个，最多 3 行；不要编号、不要解释、不要加引号。"

    try:
        llm = get_llm("consultation_followup", temperature=0.5, streaming=False)
        resp = await llm.ainvoke(
            [SystemMessage(content=FOLLOWUP_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        questions = _parse_questions(_msg_text(resp))
    except Exception as exc:
        logger.warning("consultation.followup_failed", error=str(exc)[:200])
        questions = []
    return {"followups": questions}


def _parse_questions(text: str) -> list[str]:
    """把「每行一个问题」的纯文本解析成列表（比结构化输出更稳）。"""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip().strip(" \u3000\"'“”")
        if not line:
            continue
        line = re.sub(r"^(\d+[.、)]|[-*•])\s*", "", line).strip()
        if len(line) < 4:
            continue
        out.append(line[:60])
        if len(out) >= 3:
            break
    return out


async def emergency_node(state: ConsultationState) -> dict:
    """急诊场景：固定话术，不经过大模型。"""
    info = state.get("safety") or {}
    assessment = safety.SafetyAssessment(
        level=info.get("level", "emergency"), flags=info.get("flags") or []
    )
    return {
        "answer": safety.emergency_answer(assessment),
        "answer_mode": "emergency",
        "followups": [],
        "disclaimer": safety.DISCLAIMER,
    }
