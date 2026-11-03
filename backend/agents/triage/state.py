# backend/agents/triage/state.py

from typing import TypedDict


class TriageState(TypedDict, total=False):
    # 输入
    chief_complaint: str
    age: int | None
    gender: str | None
    duration: str | None
    history: list[dict]

    # 规则护栏
    safety: dict
    urgency: str
    red_flags: list[str]

    # LLM 结构化输出
    department: str
    differential: list[str]
    recommended_tests: list[str]
    questions: list[str]
    advice: str
    rationale: str

    # 元信息
    fallback_used: bool
