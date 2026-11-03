# backend/schemas/api.py
# API 请求 / 响应模型（Pydantic v2）。

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

Urgency = Literal["emergency", "urgent", "routine"]


# ── 认证 ──────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="登录名")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    display_name: str | None = Field(None, description="昵称")
    age: int | None = Field(None, ge=0, le=120)
    gender: str | None = Field(None, description="male / female / other")


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str | None = None
    role: str = "patient"
    age: int | None = None
    gender: str | None = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ── 会话 ──────────────────────────────────────────────────────
class SessionCreate(BaseModel):
    title: str | None = Field(None, max_length=60)
    chief_complaint: str | None = Field(None, max_length=1000)


class SessionOut(BaseModel):
    id: UUID
    title: str
    chief_complaint: str | None = None
    department: str | None = None
    urgency: str = "routine"
    status: str = "active"
    summary: str | None = None
    message_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    meta: dict = {}
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class SessionDetail(BaseModel):
    session: SessionOut
    messages: list[MessageOut] = []
    triage: dict | None = None
    has_record: bool = False


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=60)


# ── 问诊对话 ──────────────────────────────────────────────────
class ChatRequest(BaseModel):
    session_id: UUID
    message: str = Field(..., min_length=1, max_length=2000)
    department: str | None = Field(None, description="限定检索的科室（可选）")
    enable_retrieval: bool = Field(True, description="是否检索知识库")


class Citation(BaseModel):
    case_id: int
    hospital: str = ""
    department: str = ""
    disease: str = ""
    snippet: str = ""
    similarity: float = 0.0
    source_url: str = ""


class SafetyOut(BaseModel):
    level: str = "routine"
    flags: list[str] = []
    advice: str = ""
    disclaimer: str = ""


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    answer_mode: str = "rag"         # rag / llm_direct / emergency / chitchat
    urgency: str = "routine"
    citations: list[Citation] = []
    followups: list[str] = []
    confidence: float = 0.0
    coverage: str = "none"
    safety: SafetyOut | None = None
    disclaimer: str = ""


# ── 分诊 ──────────────────────────────────────────────────────
class TriageRequest(BaseModel):
    chief_complaint: str = Field(..., min_length=2, max_length=1000)
    age: int | None = Field(None, ge=0, le=120)
    gender: str | None = None
    duration: str | None = Field(None, max_length=60, description="病程，如「3天」")
    session_id: UUID | None = None


class TriageResponse(BaseModel):
    department: str
    urgency: str
    red_flags: list[str] = []
    differential: list[str] = []
    recommended_tests: list[str] = []
    questions: list[str] = []
    advice: str = ""
    rationale: str = ""
    safety_level: str = "routine"
    disclaimer: str = ""


# ── 病历 ──────────────────────────────────────────────────────
class RecordGenerateRequest(BaseModel):
    session_id: UUID


class RecordUpdateRequest(BaseModel):
    chief_complaint: str | None = None
    present_illness: str | None = None
    past_history: str | None = None
    allergy_history: str | None = None
    physical_exam: str | None = None
    assessment: str | None = None
    plan: str | None = None
    diagnosis: str | None = None
    status: str | None = None


class RecordOut(BaseModel):
    id: int
    session_id: UUID
    chief_complaint: str | None = None
    present_illness: str | None = None
    past_history: str | None = None
    allergy_history: str | None = None
    physical_exam: str | None = None
    assessment: str | None = None
    plan: str | None = None
    diagnosis: str | None = None
    status: str = "draft"
    soap: dict = {}
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


# ── 病例库 ────────────────────────────────────────────────────
class CaseItem(BaseModel):
    case_id: int
    hospital: str = ""
    department: str = ""
    disease: str = ""
    snippet: str = ""
    help_wanted: str = ""


class CasePage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CaseItem] = []


class StatsOut(BaseModel):
    cases: int = 0
    qa_pairs: int = 0
    chunks: int = 0
    departments: int = 0
    users: int = 0
    sessions: int = 0
    records: int = 0
