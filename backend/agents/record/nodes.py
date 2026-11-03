# backend/agents/record/nodes.py

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.record.prompts import RECORD_SYSTEM_PROMPT, RECORD_USER_TEMPLATE
from backend.agents.record.state import RecordState
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.schemas.agent_outputs import SOAPOutput

logger = get_logger(__name__)


def _dialogue_text(messages: list[dict], max_chars: int = 7000) -> str:
    lines = []
    used = 0
    for m in messages:
        role = "患者" if m.get("role") == "user" else "助手"
        content = " ".join((m.get("content") or "").split())
        line = f"{role}：{content}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines) if lines else "（无有效对话）"


async def generate_record_node(state: RecordState) -> dict:
    triage = state.get("triage") or {}
    triager = (
        f"建议科室：{triage.get('department', '未提供')}；"
        f"紧急程度：{triage.get('urgency', '未提供')}；"
        f"红旗症状：{'、'.join(triage.get('red_flags') or []) or '无'}"
        if triage
        else "（本次未做分诊）"
    )

    prompt = RECORD_USER_TEMPLATE.format(
        triager=triager, dialogue=_dialogue_text(state.get("messages") or [])
    )

    try:
        structured = get_structured_llm("record", SOAPOutput)
        out: SOAPOutput = await structured.ainvoke(
            [SystemMessage(content=RECORD_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        return {"soap": out.model_dump(), "fallback_used": False}
    except Exception as exc:
        logger.error("record.llm_failed", error=str(exc)[:300])
        return {"soap": _fallback_soap(state.get("messages") or []), "fallback_used": True}


def _fallback_soap(messages: list[dict]) -> dict:
    """大模型不可用时的兜底病历：只做客观摘录，不生成医学判断。"""
    user_texts = [" ".join((m.get("content") or "").split()) for m in messages if m.get("role") == "user"]
    chief = user_texts[0][:40] if user_texts else "未提供"
    return {
        "chief_complaint": chief,
        "present_illness": "；".join(user_texts[:5]) or "未提供",
        "past_history": "未提供",
        "allergy_history": "未提供",
        "physical_exam": "未提供（线上问诊，无体格检查）",
        "assessment": "信息不足以形成初步评估，建议线下就诊由医生面诊判断。",
        "plan": "建议到相应科室门诊就诊，完善检查后由医生制定诊疗方案。",
        "diagnosis": "待明确",
        "summary": chief,
    }
