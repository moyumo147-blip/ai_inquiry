# backend/agents/record/state.py

from typing import TypedDict


class RecordState(TypedDict, total=False):
    session_id: str
    messages: list[dict]      # [{role, content}]
    triage: dict | None       # 分诊结果（可为空）
    soap: dict                # 结构化病历
    fallback_used: bool
    error: str
