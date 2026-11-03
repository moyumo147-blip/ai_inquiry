# backend/db/migrations.py
# 启动时自动执行的幂等迁移（CREATE ... IF NOT EXISTS），
# 只新增问诊业务表，不动已有的 medical_cases / qa_pairs / case_chunks 知识库。

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.db.session import engine

logger = get_logger(__name__)

_DDL: list[str] = [
    # 扩展（知识库已装，重复执行无副作用）
    "CREATE EXTENSION IF NOT EXISTS vector",
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    # ── 用户 ──
    """
    CREATE TABLE IF NOT EXISTS users (
        id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        username      TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name  TEXT,
        role          TEXT NOT NULL DEFAULT 'patient',
        age           INTEGER,
        gender        TEXT,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # ── 问诊会话 ──
    """
    CREATE TABLE IF NOT EXISTS consult_sessions (
        id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        title           TEXT NOT NULL DEFAULT '新问诊',
        chief_complaint TEXT,
        department      TEXT,
        urgency         TEXT NOT NULL DEFAULT 'routine',
        status          TEXT NOT NULL DEFAULT 'active',
        summary         TEXT,
        message_count   INTEGER NOT NULL DEFAULT 0,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_consult_sessions_user ON consult_sessions(user_id, updated_at DESC)",
    "ALTER TABLE consult_sessions ADD COLUMN IF NOT EXISTS summary_message_id BIGINT NOT NULL DEFAULT 0",
    # ── 会话消息 ──
    """
    CREATE TABLE IF NOT EXISTS consult_messages (
        id         BIGSERIAL PRIMARY KEY,
        session_id UUID NOT NULL REFERENCES consult_sessions(id) ON DELETE CASCADE,
        role       TEXT NOT NULL,
        content    TEXT NOT NULL,
        meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_consult_messages_session ON consult_messages(session_id, id)",
    # ── 分诊记录 ──
    """
    CREATE TABLE IF NOT EXISTS triage_records (
        id              BIGSERIAL PRIMARY KEY,
        session_id      UUID REFERENCES consult_sessions(id) ON DELETE CASCADE,
        user_id         UUID NOT NULL,
        chief_complaint TEXT NOT NULL,
        department      TEXT,
        urgency         TEXT NOT NULL DEFAULT 'routine',
        red_flags       JSONB NOT NULL DEFAULT '[]'::jsonb,
        differential    JSONB NOT NULL DEFAULT '[]'::jsonb,
        recommended_tests JSONB NOT NULL DEFAULT '[]'::jsonb,
        questions       JSONB NOT NULL DEFAULT '[]'::jsonb,
        advice          TEXT,
        safety_level    TEXT,
        raw             JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_triage_session ON triage_records(session_id, created_at DESC)",
    # ── 电子病历（SOAP）──
    """
    CREATE TABLE IF NOT EXISTS medical_records (
        id              BIGSERIAL PRIMARY KEY,
        session_id      UUID NOT NULL UNIQUE REFERENCES consult_sessions(id) ON DELETE CASCADE,
        user_id         UUID NOT NULL,
        chief_complaint TEXT,
        present_illness TEXT,
        past_history    TEXT,
        allergy_history TEXT,
        physical_exam   TEXT,
        assessment      TEXT,
        plan            TEXT,
        diagnosis       TEXT,
        soap            JSONB NOT NULL DEFAULT '{}'::jsonb,
        status          TEXT NOT NULL DEFAULT 'draft',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_medical_records_user ON medical_records(user_id, created_at DESC)",
    # 知识库检索辅助索引（病例描述关键词检索）
    "CREATE INDEX IF NOT EXISTS idx_cases_desc_trgm ON medical_cases USING gin (patient_description gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS idx_cases_department ON medical_cases (department)",
]


async def run_migrations() -> None:
    async with engine.begin() as conn:
        for stmt in _DDL:
            try:
                await conn.execute(text(stmt))
            except Exception as exc:  # 单条失败不阻断启动（例如扩展权限不足）
                logger.warning("db.migration_statement_failed", error=str(exc)[:300])
    logger.info("db.migrations_done", statements=len(_DDL))
