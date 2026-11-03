# backend/agents/consultation/state.py

from typing import TypedDict


class ConsultationState(TypedDict, total=False):
    # ── 输入 ──
    session_id: str
    user_id: str
    query: str
    history: list[dict]          # [{role, content}]，时间正序
    summary: str | None          # 既往对话摘要（长会话压缩后的产物）
    age: int | None
    gender: str | None
    department: str | None       # 意向科室（限定检索范围）
    enable_retrieval: bool
    session_complaint: str | None   # 会话建立时的主诉（分诊用）
    session_urgency: str | None     # 会话建立时的紧急度（急诊会话保持急诊口径）

    # ── 规则护栏 ──
    safety: dict
    urgency: str

    # ── 路由 ──
    intent: str                  # medical / chitchat / record

    # ── 检索结果 ──
    context: str                 # 拼好的参考病例文本
    citations: list[dict]
    confidence: float
    coverage: str

    # ── 生成结果 ──
    answer: str
    answer_mode: str             # rag / llm_direct / emergency / chitchat / record_hint
    followups: list[str]
    disclaimer: str
    error: str
