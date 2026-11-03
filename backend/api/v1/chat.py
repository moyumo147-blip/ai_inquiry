# backend/api/v1/chat.py
# 问诊对话接口：普通返回 + SSE 流式返回。

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from langgraph.graph import StateGraph  # noqa: F401  (类型提示用)
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.agents.consultation.graph import build_consultation_graph
from backend.core import safety
from backend.core.summarizer import maybe_summarize
from backend.core.logger import get_logger
from backend.db import repositories as repo
from backend.db.session import AsyncSessionLocal, get_db
from backend.dependencies import get_current_user
from backend.schemas.api import ChatRequest, ChatResponse, Citation, SafetyOut

router = APIRouter(prefix="/chat", tags=["问诊对话"])
logger = get_logger(__name__)

_PROGRESS_LABELS = {
    "safety_check": "安全评估中…",
    "classify": "理解您的问题…",
    "retrieve": "检索相似病例…",
    "generate": "生成建议…",
    "suggest_followup": "整理要追问的信息…",
    "emergency": "识别到紧急信号…",
}


def _to_citations(raw: list[dict]) -> list[Citation]:
    out: list[Citation] = []
    for item in raw or []:
        try:
            out.append(
                Citation(
                    case_id=int(item.get("case_id", 0)),
                    hospital=item.get("hospital", "") or "",
                    department=item.get("department", "") or "",
                    disease=(item.get("disease", "") or "")[:60],
                    snippet=item.get("snippet", "") or "",
                    similarity=float(item.get("similarity", 0.0) or 0.0),
                    source_url=item.get("source_url", "") or "",
                )
            )
        except Exception:
            continue
    return out


def _initial_state(req: ChatRequest, current_user: dict, history: list[dict], session) -> dict:
    return {
        "session_id": str(req.session_id),
        "user_id": current_user["user_id"],
        "query": req.message,
        "history": history,
        "summary": session.summary or "",
        "age": current_user.get("age"),
        "gender": current_user.get("gender"),
        "department": req.department,
        "enable_retrieval": req.enable_retrieval,
        "session_complaint": session.chief_complaint,
        "session_urgency": session.urgency,
        "followups": [],
    }


async def _prepare(db: AsyncSession, req: ChatRequest, current_user: dict):
    session = await repo.get_session(db, req.session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"},
        )
    history = await repo.history_after(db, session.id, session.summary_message_id or 0, limit=10)
    return session, history


async def _persist_assistant(db: AsyncSession, session, state: dict) -> None:
    meta = {
        "answer_mode": state.get("answer_mode", ""),
        "urgency": state.get("urgency", "routine"),
        "confidence": state.get("confidence", 0.0),
        "coverage": state.get("coverage", "none"),
        "followups": state.get("followups") or [],
        "citations": [
            {
                "case_id": c.get("case_id"),
                "hospital": c.get("hospital"),
                "department": c.get("department"),
                "disease": (c.get("disease") or "")[:60],
                "snippet": c.get("snippet"),
            }
            for c in (state.get("citations") or [])
        ],
    }
    await repo.save_message(
        db, session.id, "assistant", state.get("answer", ""), meta=meta
    )
    await repo.touch_session(db, session, inc_messages=2)


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """发送一条消息，返回完整回答（非流式）。"""
    session, history = await _prepare(db, req, current_user)

    # 标题：首条消息截取
    if (session.message_count or 0) == 0:
        await repo.update_session(db, session, title=req.message[:20])

    await repo.save_message(db, session.id, "user", req.message)

    graph = build_consultation_graph(db)
    try:
        state = await graph.ainvoke(_initial_state(req, current_user, history, session))
    except Exception as exc:
        logger.error("chat.invoke_failed", error=str(exc)[:500], exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "AGENT_ERROR", "message": "问诊服务暂时不可用，请稍后重试"},
        )

    await _persist_assistant(db, session, state)
    await maybe_summarize(db, session)

    safety_dict = state.get("safety") or {}
    return ChatResponse(
        session_id=session.id,
        answer=state.get("answer", ""),
        answer_mode=state.get("answer_mode", "llm_direct"),
        urgency=state.get("urgency", "routine"),
        citations=_to_citations(state.get("citations") or []),
        followups=state.get("followups") or [],
        confidence=float(state.get("confidence", 0.0) or 0.0),
        coverage=state.get("coverage", "none"),
        safety=SafetyOut(
            level=safety_dict.get("level", "routine"),
            flags=safety_dict.get("flags") or [],
            advice=safety_dict.get("advice", ""),
            disclaimer=safety_dict.get("disclaimer", safety.DISCLAIMER),
        ),
        disclaimer=safety.DISCLAIMER,
    )


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """SSE 流式问诊：progress / token / meta / done 四类事件。"""

    async def event_generator():
        accum: dict = {}
        async with AsyncSessionLocal() as db:
            session = await repo.get_session(db, req.session_id, current_user["user_id"])
            if session is None:
                yield {"data": json.dumps({"type": "error", "message": "会话不存在"}, ensure_ascii=False)}
                return

            history = await repo.history_after(db, session.id, session.summary_message_id or 0, limit=10)
            if (session.message_count or 0) == 0:
                await repo.update_session(db, session, title=req.message[:20])
            await repo.save_message(db, session.id, "user", req.message)
            await db.commit()

            graph = build_consultation_graph(db)
            state_in = _initial_state(req, current_user, history, session)

            try:
                async for event in graph.astream_events(state_in):
                    evt = event.get("event")
                    node = (event.get("metadata") or {}).get("langgraph_node", "")

                    if evt == "on_chain_start" and node in _PROGRESS_LABELS:
                        yield {
                            "data": json.dumps(
                                {"type": "progress", "stage": _PROGRESS_LABELS[node]},
                                ensure_ascii=False,
                            )
                        }

                    elif evt == "on_chat_model_stream" and node == "generate":
                        chunk = (event.get("data") or {}).get("chunk")
                        content = getattr(chunk, "content", "") if chunk else ""
                        if isinstance(content, str) and content:
                            yield {
                                "data": json.dumps({"type": "token", "content": content}, ensure_ascii=False)
                            }

                    elif evt == "on_chain_end" and node:
                        output = (event.get("data") or {}).get("output")
                        if isinstance(output, dict):
                            accum.update(output)
            except Exception as exc:
                logger.error("chat.stream_failed", error=str(exc)[:500], exc_info=True)
                await db.rollback()
                yield {
                    "data": json.dumps(
                        {"type": "error", "message": "流式输出异常，请重试或使用普通接口"},
                        ensure_ascii=False,
                    )
                }
                return

            answer = accum.get("answer") or ""
            if not answer:
                answer = "抱歉，本次没有生成有效回答，请重试或换一种描述。"
                accum["answer"] = answer

            await _persist_assistant(db, session, accum)
            await maybe_summarize(db, session)
            await db.commit()

            safety_dict = accum.get("safety") or {}
            yield {
                "data": json.dumps(
                    {
                        "type": "meta",
                        "session_id": str(session.id),
                        "answer_mode": accum.get("answer_mode", "llm_direct"),
                        "urgency": accum.get("urgency", "routine"),
                        "confidence": float(accum.get("confidence", 0.0) or 0.0),
                        "coverage": accum.get("coverage", "none"),
                        "citations": [
                            {
                                "case_id": c.get("case_id"),
                                "hospital": c.get("hospital"),
                                "department": c.get("department"),
                                "disease": (c.get("disease") or "")[:60],
                                "snippet": c.get("snippet"),
                            }
                            for c in (accum.get("citations") or [])
                        ],
                        "followups": accum.get("followups") or [],
                        "safety": {
                            "level": safety_dict.get("level", "routine"),
                            "flags": safety_dict.get("flags") or [],
                            "advice": safety_dict.get("advice", ""),
                        },
                        "disclaimer": safety.DISCLAIMER,
                    },
                    ensure_ascii=False,
                )
            }
            yield {"data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())
