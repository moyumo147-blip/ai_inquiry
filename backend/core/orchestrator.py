# backend/core/orchestrator.py
# 会话级编排：新会话「预问诊」= 分诊 Agent + 开场白落库 + 会话字段回写。
# 之后的每一轮对话由 Consultation Agent 自己路由（安全 → 检索 → 生成 → 追问）。

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.triage.graph import build_triage_graph
from backend.core.logger import get_logger
from backend.db import repositories as repo
from backend.models.entities import ConsultSession

logger = get_logger(__name__)

URGENCY_LABEL = {"emergency": "立即急诊", "urgent": "24 小时内就诊", "routine": "常规门诊"}


class Orchestrator:
    """把「分诊 → 问诊 → 病历」串起来的最薄一层编排。"""

    @staticmethod
    async def pre_consult(
        db: AsyncSession,
        session: ConsultSession,
        chief_complaint: str,
        age: int | None = None,
        gender: str | None = None,
        duration: str | None = None,
    ) -> dict:
        """对主诉做分诊，写入 triage_records，并回写会话科室/紧急度。"""
        graph = build_triage_graph()
        state = await graph.ainvoke(
            {
                "chief_complaint": chief_complaint,
                "age": age,
                "gender": gender,
                "duration": duration,
            }
        )

        triage = {
            "department": state.get("department"),
            "urgency": state.get("urgency", "routine"),
            "red_flags": state.get("red_flags", []),
            "differential": state.get("differential", []),
            "recommended_tests": state.get("recommended_tests", []),
            "questions": state.get("questions", []),
            "advice": state.get("advice", ""),
            "rationale": state.get("rationale", ""),
            "safety_level": (state.get("safety") or {}).get("level", "routine"),
        }

        try:
            await repo.save_triage(
                db,
                user_id=session.user_id,
                session_id=session.id,
                chief_complaint=chief_complaint,
                department=triage["department"],
                urgency=triage["urgency"],
                red_flags=triage["red_flags"],
                differential=triage["differential"],
                recommended_tests=triage["recommended_tests"],
                questions=triage["questions"],
                advice=triage["advice"],
                safety_level=triage["safety_level"],
                raw={"rationale": triage["rationale"], "fallback_used": state.get("fallback_used", False)},
            )
            await repo.update_session(
                db,
                session,
                department=triage["department"],
                urgency=triage["urgency"],
                chief_complaint=chief_complaint,
            )
        except Exception as exc:
            logger.error("orchestrator.persist_triage_failed", error=str(exc)[:300])

        logger.info(
            "orchestrator.pre_consult_done",
            session_id=str(session.id),
            department=triage["department"],
            urgency=triage["urgency"],
        )
        return triage

    @staticmethod
    def welcome_message(triage: dict, chief_complaint: str) -> str:
        """把分诊结果转成一条自然的开场白（存库 + 前端展示）。"""
        dept = triage.get("department") or "全科医学科"
        urgency = triage.get("urgency", "routine")
        label = URGENCY_LABEL.get(urgency, urgency)
        flags = triage.get("red_flags") or []

        lines = [f"已收到您的主诉：**{chief_complaint.strip()[:60]}**。", ""]
        lines.append(f"🧭 **分诊建议**：{dept}｜{label}")

        if flags:
            lines.append(f"⚠️ 需要留意：{'、'.join(flags)}")

        if triage.get("advice"):
            lines.append("")
            lines.append(f"**下一步**：{triage['advice']}")

        questions = triage.get("questions") or []
        if questions:
            lines.append("")
            lines.append("为了判断得更准确，请补充：")
            for i, q in enumerate(questions[:3], 1):
                lines.append(f"{i}. {q}")

        lines.append("")
        lines.append(
            "> 我是 AI 问诊助手，提供的是就医方向与健康科普，不能替代医生面诊；"
            "如出现胸痛、呼吸困难、意识不清等紧急情况，请立即拨打 120。"
        )
        return "\n".join(lines)


orchestrator = Orchestrator()
