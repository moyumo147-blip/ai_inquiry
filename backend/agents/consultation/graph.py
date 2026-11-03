# backend/agents/consultation/graph.py
# 问诊 Agent 状态图：
#   START → safety_check ─┬─(emergency)→ emergency → END
#                         └→ classify ─┬─(record/chitchat)→ generate → suggest_followup → END
#                                      └─(medical)→ retrieve → generate → suggest_followup → END

from functools import partial

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.consultation.nodes import (
    classify_node,
    emergency_node,
    generate_node,
    retrieve_node,
    safety_check_node,
    suggest_followup_node,
)
from backend.agents.consultation.state import ConsultationState


def _route_after_safety(state: ConsultationState) -> str:
    return "emergency" if (state.get("urgency") == "emergency") else "classify"


def _route_after_classify(state: ConsultationState) -> str:
    return "retrieve" if state.get("intent", "medical") == "medical" else "generate"


def build_consultation_graph(db: AsyncSession):
    """每次请求构建一次图（db 会话按请求绑定）。"""
    builder = StateGraph(ConsultationState)

    builder.add_node("safety_check", safety_check_node)
    builder.add_node("classify", classify_node)
    builder.add_node("retrieve", partial(retrieve_node, db=db))
    builder.add_node("generate", generate_node)
    builder.add_node("suggest_followup", suggest_followup_node)
    builder.add_node("emergency", emergency_node)

    builder.add_edge(START, "safety_check")
    builder.add_conditional_edges(
        "safety_check",
        _route_after_safety,
        {"emergency": "emergency", "classify": "classify"},
    )
    builder.add_conditional_edges(
        "classify",
        _route_after_classify,
        {"retrieve": "retrieve", "generate": "generate"},
    )
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", "suggest_followup")
    builder.add_edge("suggest_followup", END)
    builder.add_edge("emergency", END)

    return builder.compile()


if __name__ == "__main__":
    # 仅验证图结构（不连数据库）
    from langgraph.graph import StateGraph as _SG  # noqa: F401

    print("咨询图节点：safety_check, classify, retrieve, generate, suggest_followup, emergency")
