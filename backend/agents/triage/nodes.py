# backend/agents/triage/nodes.py
# 分诊节点：规则护栏 → LLM 结构化分诊 → 结果合并（规则可升级紧急度）。

from langchain_core.messages import HumanMessage, SystemMessage

from backend.agents.triage.prompts import TRIAGE_SYSTEM_PROMPT, TRIAGE_USER_TEMPLATE
from backend.agents.triage.state import TriageState
from backend.core import safety
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.schemas.agent_outputs import TriageOutput

logger = get_logger(__name__)

_LEVEL_ORDER = {"routine": 0, "urgent": 1, "emergency": 2}


def _max_urgency(a: str, b: str) -> str:
    return a if _LEVEL_ORDER.get(a, 0) >= _LEVEL_ORDER.get(b, 0) else b


async def safety_node(state: TriageState) -> dict:
    """红旗症状规则扫描（不依赖大模型）。"""
    text = " ".join(
        filter(None, [state.get("chief_complaint", ""), state.get("duration") or ""])
    )
    assessment = safety.assess(text)
    logger.info(
        "triage.safety_done",
        level=assessment.level,
        flags=assessment.flags,
    )
    return {
        "safety": assessment.to_dict(),
        "urgency": assessment.level,
        "red_flags": assessment.flags,
    }


async def triage_node(state: TriageState) -> dict:
    """LLM 结构化分诊，失败时退回规则模板。"""
    safety_info = state.get("safety") or {}
    red_flags = state.get("red_flags") or []

    prompt = TRIAGE_USER_TEMPLATE.format(
        age=state.get("age") if state.get("age") is not None else "未知",
        gender=state.get("gender") or "未知",
        duration=state.get("duration") or "未提供",
        complaint=state.get("chief_complaint", ""),
        red_flags="、".join(red_flags) if red_flags else "无",
    )

    try:
        structured = get_structured_llm("triage", TriageOutput)
        out: TriageOutput = await structured.ainvoke(
            [SystemMessage(content=TRIAGE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
    except Exception as exc:
        logger.error("triage.llm_failed", error=str(exc)[:300])
        return {
            **rule_based_fallback(state),
            "fallback_used": True,
        }

    urgency = _max_urgency(out.urgency, safety_info.get("level", "routine"))
    return {
        "department": out.department,
        "urgency": urgency,
        "red_flags": _merge_flags(red_flags, out.red_flags),
        "differential": out.differential,
        "recommended_tests": out.recommended_tests,
        "questions": out.questions[:3],
        "advice": out.advice,
        "rationale": out.rationale,
        "fallback_used": False,
    }


def _merge_flags(rule_flags: list[str], llm_flags: list[str]) -> list[str]:
    merged: list[str] = []
    for flag in list(rule_flags) + list(llm_flags or []):
        flag = (flag or "").strip()
        if flag and flag not in merged:
            merged.append(flag)
    return merged[:8]


# ── 规则兜底：LLM 不可用时的分诊表 ────────────────────────────
_DEPARTMENT_RULES: list[tuple[str, str]] = [
    (r"(胸痛|心悸|心慌|血压|心前区|心跳)", "心血管内科"),
    (r"(咳嗽|咳痰|发烧|发热|气喘|呼吸困难|肺炎|感冒)", "呼吸内科"),
    (r"(腹痛|胃痛|腹泻|呕吐|恶心|反酸|便秘|便血|肝|胆)", "消化内科"),
    (r"(头痛|头晕|眩晕|手脚麻|抽搐|失眠|半身|说话不清)", "神经内科"),
    (r"(皮疹|瘙痒|红斑|湿疹|痘|荨麻疹|脱发|皮肤)", "皮肤科"),
    (r"(骨折|扭伤|腰痛|颈椎|关节|膝盖|肩痛|摔伤)", "骨科"),
    (r"(孩子|儿童|婴儿|宝宝|小儿|新生儿)", "儿科"),
    (r"(月经|怀孕|孕|阴道|白带|乳腺|产检)", "妇产科"),
    (r"(耳鸣|耳痛|鼻塞|流鼻涕|咽喉|嗓子|扁桃体|声音嘶哑)", "耳鼻咽喉科"),
    (r"(眼睛|视力|眼红|眼痛|流泪|视物模糊)", "眼科"),
    (r"(焦虑|抑郁|情绪|心理|睡不着|精神)", "精神心理科"),
    (r"(牙痛|口腔|牙龈|溃疡|舌头)", "口腔科"),
    (r"(尿频|尿痛|血尿|排尿|肾|前列腺|水肿)", "泌尿外科"),
    (r"(甲状腺|血糖|糖尿病|肥胖|乏力|月经不调|内分泌)", "内分泌科"),
]


def rule_based_fallback(state: TriageState) -> dict:
    text = state.get("chief_complaint", "")
    department = "全科医学科"
    for pattern, dept in _DEPARTMENT_RULES:
        import re

        if re.search(pattern, text):
            department = dept
            break

    safety_info = state.get("safety") or {}
    urgency = safety_info.get("level", "routine")
    return {
        "department": department,
        "urgency": urgency,
        "differential": [],
        "recommended_tests": [],
        "questions": ["症状持续多久了？", "有没有发热、呕吐等伴随症状？", "既往有什么慢性病或正在吃什么药？"],
        "advice": (
            "建议先到「{}」门诊就诊；若症状加重或出现胸痛、呼吸困难、意识改变，请立即急诊。".format(
                department
            )
        ),
        "rationale": "规则模板兜底（大模型暂不可用）",
    }
