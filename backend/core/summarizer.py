# backend/core/summarizer.py
# 长会话摘要压缩：消息数超过阈值后，把「较早的对话」压成一段就诊摘要写入会话，
# 之后 Prompt 只带「摘要 + 最近若干条原文」，避免上下文无限膨胀。

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.core.llm_factory import get_llm
from backend.core.logger import get_logger
from backend.db import repositories as repo
from backend.models.entities import ConsultSession

logger = get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = """你是病历摘要助手。把多轮问诊对话压缩成给医生看的「就诊摘要」，供后续问诊引用。

【保留】
1. 患者基本信息（年龄、性别）
2. 主诉、起病时间与病程
3. 关键症状、诱因、伴随症状、症状变化
4. 既往史、用药、过敏史
5. 已做检查及结果、已给出的建议

【丢弃】
寒暄、重复表述、助手的长篇科普与免责声明。

【要求】
- 第三人称、条目式，不超过 300 字；
- 没有的信息写「未提供」，不要编造，也不要根据「常见情况」推测（如性别、年龄、病程）；
- 只输出摘要正文，不要加标题或解释。"""

SUMMARY_USER_TEMPLATE = """【已有摘要】
{existing}

【新增对话】
{dialogue}

请输出合并后的最新摘要。"""


def _msg_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


async def maybe_summarize(db: AsyncSession, session: ConsultSession) -> str | None:
    """满足条件时压缩历史消息；返回新摘要（或 None 表示未触发）。"""
    settings = get_settings()
    if (session.message_count or 0) < settings.summary_trigger_messages:
        return None

    after_id = session.summary_message_id or 0
    rows = await repo.messages_after(db, session.id, after_id, limit=200)
    keep = settings.summary_keep_recent
    if len(rows) <= keep:
        return None

    to_compress = rows[:-keep]
    if len(to_compress) < 4:  # 太短不值得摘要
        return None

    dialogue = "\n".join(
        f"{'患者' if m.role == 'user' else '助手'}：{' '.join((m.content or '').split())[:400]}"
        for m in to_compress
    )
    prompt = SUMMARY_USER_TEMPLATE.format(
        existing=session.summary or "（无）", dialogue=dialogue[:6000]
    )

    try:
        llm = get_llm("summary", temperature=0.2)
        resp = await llm.ainvoke(
            [SystemMessage(content=SUMMARY_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
        summary = _msg_text(resp).strip()
    except Exception as exc:
        logger.warning("summarizer.failed", error=str(exc)[:200])
        return None

    if not summary:
        return None

    await repo.save_summary(db, session, summary[:1200], to_compress[-1].id)
    logger.info(
        "summarizer.done",
        session_id=str(session.id),
        compressed=len(to_compress),
        upto_message_id=to_compress[-1].id,
        summary_chars=len(summary),
    )
    return summary
