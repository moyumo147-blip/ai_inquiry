-- scripts/init_db.sql
-- AI 问诊系统 · 业务表结构（幂等）
-- 说明：
--   1. 知识库三张表（medical_cases / qa_pairs / case_chunks）由入库脚本 main.py 创建并已灌好数据，
--      本文件不会写入、也不会重建它们，只补充问诊业务表。
--   2. 后端启动时会自动执行同样的 DDL（backend/db/migrations.py），本文件用于手工建库/审阅。
--
-- 用法：psql -U postgres -d postgres -f scripts/init_db.sql

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── 用户 ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT,
    role          TEXT NOT NULL DEFAULT 'patient',
    age           INTEGER,
    gender        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 问诊会话 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS consult_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT '新问诊',
    chief_complaint TEXT,
    department      TEXT,
    urgency         TEXT NOT NULL DEFAULT 'routine',
    status          TEXT NOT NULL DEFAULT 'active',
    summary         TEXT,
    summary_message_id BIGINT NOT NULL DEFAULT 0,
    message_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consult_sessions_user ON consult_sessions(user_id, updated_at DESC);

-- ── 会话消息 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS consult_messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES consult_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    meta       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_consult_messages_session ON consult_messages(session_id, id);

-- ── 分诊记录 ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS triage_records (
    id                BIGSERIAL PRIMARY KEY,
    session_id        UUID REFERENCES consult_sessions(id) ON DELETE CASCADE,
    user_id           UUID NOT NULL,
    chief_complaint   TEXT NOT NULL,
    department        TEXT,
    urgency           TEXT NOT NULL DEFAULT 'routine',
    red_flags         JSONB NOT NULL DEFAULT '[]'::jsonb,
    differential      JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommended_tests JSONB NOT NULL DEFAULT '[]'::jsonb,
    questions         JSONB NOT NULL DEFAULT '[]'::jsonb,
    advice            TEXT,
    safety_level      TEXT,
    raw               JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_triage_session ON triage_records(session_id, created_at DESC);

-- ── 电子病历（SOAP）───────────────────────────────────────────
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
);
CREATE INDEX IF NOT EXISTS idx_medical_records_user ON medical_records(user_id, created_at DESC);

-- ── 知识库检索辅助索引（只建索引，不改数据）─────────────────
CREATE INDEX IF NOT EXISTS idx_cases_desc_trgm ON medical_cases USING gin (patient_description gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_cases_department ON medical_cases (department);
