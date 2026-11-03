# backend/agents/record/graph.py

from langgraph.graph import END, START, StateGraph

from backend.agents.record.nodes import generate_record_node
from backend.agents.record.state import RecordState


def build_record_graph():
    builder = StateGraph(RecordState)
    builder.add_node("generate_record", generate_record_node)
    builder.add_edge(START, "generate_record")
    builder.add_edge("generate_record", END)
    return builder.compile()
