# backend/agents/triage/graph.py

from langgraph.graph import END, START, StateGraph

from backend.agents.triage.nodes import safety_node, triage_node
from backend.agents.triage.state import TriageState


def build_triage_graph():
    builder = StateGraph(TriageState)
    builder.add_node("safety_check", safety_node)
    builder.add_node("triage", triage_node)

    builder.add_edge(START, "safety_check")
    builder.add_edge("safety_check", "triage")
    builder.add_edge("triage", END)
    return builder.compile()


if __name__ == "__main__":
    graph = build_triage_graph()
    print("分诊图节点：", list(graph.nodes.keys()))
