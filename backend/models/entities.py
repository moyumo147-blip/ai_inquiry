# backend/models/entities.py
# SQLAlchemy ORM 实体：只映射「问诊业务表」，知识库三张表仍用原生 SQL 查询。

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="patient")
    age: Mapped[int | None] = mapped_column(Integer)
    gender: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())


class ConsultSession(Base):
    __tablename__ = "consult_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, default="新问诊")
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String)
    urgency: Mapped[str] = mapped_column(String, default="routine")
    status: Mapped[str] = mapped_column(String, default="active")
    summary: Mapped[str | None] = mapped_column(Text)
    summary_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )


class ConsultMessage(Base):
    __tablename__ = "consult_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consult_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())


class TriageRecord(Base):
    __tablename__ = "triage_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consult_sessions.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chief_complaint: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str | None] = mapped_column(String)
    urgency: Mapped[str] = mapped_column(String, default="routine")
    red_flags: Mapped[list] = mapped_column(JSONB, default=list)
    differential: Mapped[list] = mapped_column(JSONB, default=list)
    recommended_tests: Mapped[list] = mapped_column(JSONB, default=list)
    questions: Mapped[list] = mapped_column(JSONB, default=list)
    advice: Mapped[str | None] = mapped_column(Text)
    safety_level: Mapped[str | None] = mapped_column(String)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())


class MedicalRecord(Base):
    __tablename__ = "medical_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consult_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    chief_complaint: Mapped[str | None] = mapped_column(Text)
    present_illness: Mapped[str | None] = mapped_column(Text)
    past_history: Mapped[str | None] = mapped_column(Text)
    allergy_history: Mapped[str | None] = mapped_column(Text)
    physical_exam: Mapped[str | None] = mapped_column(Text)
    assessment: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str | None] = mapped_column(Text)
    diagnosis: Mapped[str | None] = mapped_column(String)
    soap: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, server_default=func.now()
    )
