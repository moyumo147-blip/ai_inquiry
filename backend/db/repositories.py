# backend/db/repositories.py
# 数据访问层：用户 / 会话 / 消息 / 分诊 / 病历 的增删改查。
# API 与 Agent 不直接拼 SQL，统一走这里。

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.entities import (
    ConsultMessage,
    ConsultSession,
    MedicalRecord,
    TriageRecord,
    User,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── 用户 ──────────────────────────────────────────────────────
async def create_user(
    db: AsyncSession,
    username: str,
    password_hash: str,
    display_name: str | None = None,
    age: int | None = None,
    gender: str | None = None,
) -> User:
    user = User(
        username=username,
        password_hash=password_hash,
        display_name=display_name or username,
        age=age,
        gender=gender,
    )
    db.add(user)
    await db.flush()
    return user


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: uuid.UUID | str) -> User | None:
    return (await db.execute(select(User).where(User.id == uuid.UUID(str(user_id))))).scalar_one_or_none()


# ── 会话 ──────────────────────────────────────────────────────
async def create_session(
    db: AsyncSession, user_id: uuid.UUID | str, title: str = "新问诊", chief_complaint: str | None = None
) -> ConsultSession:
    session = ConsultSession(
        user_id=uuid.UUID(str(user_id)), title=title, chief_complaint=chief_complaint
    )
    db.add(session)
    await db.flush()
    return session


async def get_session(
    db: AsyncSession, session_id: uuid.UUID | str, user_id: uuid.UUID | str | None = None
) -> ConsultSession | None:
    stmt = select(ConsultSession).where(ConsultSession.id == uuid.UUID(str(session_id)))
    if user_id is not None:
        stmt = stmt.where(ConsultSession.user_id == uuid.UUID(str(user_id)))
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_sessions(
    db: AsyncSession, user_id: uuid.UUID | str, limit: int = 50
) -> list[ConsultSession]:
    stmt = (
        select(ConsultSession)
        .where(ConsultSession.user_id == uuid.UUID(str(user_id)))
        .order_by(desc(ConsultSession.updated_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_session(db: AsyncSession, session: ConsultSession, **fields) -> ConsultSession:
    for key, value in fields.items():
        if value is not None and hasattr(session, key):
            setattr(session, key, value)
    session.updated_at = _now()
    await db.flush()
    return session


async def touch_session(db: AsyncSession, session: ConsultSession, inc_messages: int = 0) -> None:
    session.updated_at = _now()
    session.message_count = (session.message_count or 0) + inc_messages
    await db.flush()


async def delete_session(db: AsyncSession, session: ConsultSession) -> None:
    await db.execute(delete(ConsultSession).where(ConsultSession.id == session.id))
    await db.flush()


# ── 消息 ──────────────────────────────────────────────────────
async def save_message(
    db: AsyncSession,
    session_id: uuid.UUID | str,
    role: str,
    content: str,
    meta: dict | None = None,
) -> ConsultMessage:
    msg = ConsultMessage(
        session_id=uuid.UUID(str(session_id)),
        role=role,
        content=content,
        meta=meta or {},
    )
    db.add(msg)
    await db.flush()
    return msg


async def list_messages(
    db: AsyncSession, session_id: uuid.UUID | str, limit: int = 200
) -> list[ConsultMessage]:
    stmt = (
        select(ConsultMessage)
        .where(ConsultMessage.session_id == uuid.UUID(str(session_id)))
        .order_by(ConsultMessage.id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def recent_history(
    db: AsyncSession, session_id: uuid.UUID | str, limit: int = 10
) -> list[dict]:
    """最近 N 轮消息（按时间正序），用于拼 Prompt 上下文。"""
    stmt = (
        select(ConsultMessage)
        .where(ConsultMessage.session_id == uuid.UUID(str(session_id)))
        .order_by(desc(ConsultMessage.id))
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return [{"role": m.role, "content": m.content} for m in rows]


async def history_after(
    db: AsyncSession, session_id: uuid.UUID | str, after_id: int = 0, limit: int = 10
) -> list[dict]:
    """取 id > after_id 的最近 N 条消息（摘要水位之后的原文）。"""
    stmt = (
        select(ConsultMessage)
        .where(
            ConsultMessage.session_id == uuid.UUID(str(session_id)),
            ConsultMessage.id > after_id,
        )
        .order_by(desc(ConsultMessage.id))
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    rows.reverse()
    return [{"id": m.id, "role": m.role, "content": m.content} for m in rows]


async def messages_after(
    db: AsyncSession, session_id: uuid.UUID | str, after_id: int = 0, limit: int = 200
) -> list[ConsultMessage]:
    """按时间正序取 id > after_id 的消息（供摘要压缩使用）。"""
    stmt = (
        select(ConsultMessage)
        .where(
            ConsultMessage.session_id == uuid.UUID(str(session_id)),
            ConsultMessage.id > after_id,
        )
        .order_by(ConsultMessage.id.asc())
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def save_summary(
    db: AsyncSession, session: ConsultSession, summary: str, upto_message_id: int
) -> None:
    """写入会话摘要与压缩水位（水位之前的原文不再重复送入 Prompt）。"""
    session.summary = summary
    session.summary_message_id = upto_message_id
    session.updated_at = _now()
    await db.flush()


# ── 分诊 ──────────────────────────────────────────────────────
async def save_triage(
    db: AsyncSession,
    user_id: uuid.UUID | str,
    chief_complaint: str,
    department: str | None,
    urgency: str,
    red_flags: list,
    differential: list,
    recommended_tests: list,
    questions: list,
    advice: str | None,
    safety_level: str | None,
    raw: dict,
    session_id: uuid.UUID | str | None = None,
) -> TriageRecord:
    record = TriageRecord(
        session_id=uuid.UUID(str(session_id)) if session_id else None,
        user_id=uuid.UUID(str(user_id)),
        chief_complaint=chief_complaint,
        department=department,
        urgency=urgency,
        red_flags=red_flags,
        differential=differential,
        recommended_tests=recommended_tests,
        questions=questions,
        advice=advice,
        safety_level=safety_level,
        raw=raw,
    )
    db.add(record)
    await db.flush()
    return record


async def latest_triage(
    db: AsyncSession, session_id: uuid.UUID | str
) -> TriageRecord | None:
    stmt = (
        select(TriageRecord)
        .where(TriageRecord.session_id == uuid.UUID(str(session_id)))
        .order_by(desc(TriageRecord.id))
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


# ── 病历 ──────────────────────────────────────────────────────
async def upsert_record(
    db: AsyncSession,
    session_id: uuid.UUID | str,
    user_id: uuid.UUID | str,
    data: dict,
) -> MedicalRecord:
    record = (
        await db.execute(
            select(MedicalRecord).where(MedicalRecord.session_id == uuid.UUID(str(session_id)))
        )
    ).scalar_one_or_none()

    if record is None:
        record = MedicalRecord(session_id=uuid.UUID(str(session_id)), user_id=uuid.UUID(str(user_id)))
        db.add(record)

    for field in (
        "chief_complaint",
        "present_illness",
        "past_history",
        "allergy_history",
        "physical_exam",
        "assessment",
        "plan",
        "diagnosis",
        "soap",
        "status",
    ):
        if field in data and data[field] is not None:
            setattr(record, field, data[field])
    record.updated_at = _now()
    await db.flush()
    return record


async def get_record_by_session(
    db: AsyncSession, session_id: uuid.UUID | str
) -> MedicalRecord | None:
    return (
        await db.execute(
            select(MedicalRecord).where(MedicalRecord.session_id == uuid.UUID(str(session_id)))
        )
    ).scalar_one_or_none()


async def get_record(db: AsyncSession, record_id: int) -> MedicalRecord | None:
    return (await db.execute(select(MedicalRecord).where(MedicalRecord.id == record_id))).scalar_one_or_none()


async def list_records(
    db: AsyncSession, user_id: uuid.UUID | str, limit: int = 50
) -> list[MedicalRecord]:
    stmt = (
        select(MedicalRecord)
        .where(MedicalRecord.user_id == uuid.UUID(str(user_id)))
        .order_by(desc(MedicalRecord.updated_at))
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())
