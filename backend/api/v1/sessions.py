# backend/api/v1/sessions.py

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.orchestrator import orchestrator
from backend.db import repositories as repo
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import (
    MessageOut,
    SessionCreate,
    SessionDetail,
    SessionOut,
    SessionRenameRequest,
)

router = APIRouter(prefix="/sessions", tags=["问诊会话"])


def _triage_dict(record) -> dict | None:
    if record is None:
        return None
    return {
        "department": record.department,
        "urgency": record.urgency,
        "red_flags": record.red_flags or [],
        "differential": record.differential or [],
        "recommended_tests": record.recommended_tests or [],
        "questions": record.questions or [],
        "advice": record.advice,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.post("", response_model=SessionDetail, status_code=status.HTTP_201_CREATED)
async def create_session(
    req: SessionCreate | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建问诊会话。带 chief_complaint 时会自动跑一次分诊，并生成开场白。"""
    req = req or SessionCreate()
    session = await repo.create_session(
        db,
        user_id=current_user["user_id"],
        title=req.title or (req.chief_complaint[:20] if req.chief_complaint else "新问诊"),
        chief_complaint=req.chief_complaint,
    )

    triage = None
    messages: list[MessageOut] = []

    if req.chief_complaint:
        triage = await orchestrator.pre_consult(
            db,
            session,
            req.chief_complaint,
            age=current_user.get("age"),
            gender=current_user.get("gender"),
        )
        welcome = orchestrator.welcome_message(triage, req.chief_complaint)
        msg = await repo.save_message(
            db, session.id, "assistant", welcome, meta={"type": "welcome", "triage": triage}
        )
        await repo.touch_session(db, session, inc_messages=1)
        messages.append(MessageOut.model_validate(msg))

    return SessionDetail(
        session=SessionOut.model_validate(session),
        messages=messages,
        triage=triage,
        has_record=False,
    )


@router.get("", response_model=list[SessionOut])
async def list_sessions(
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    sessions = await repo.list_sessions(db, current_user["user_id"])
    return [SessionOut.model_validate(s) for s in sessions]


@router.get("/{session_id}", response_model=SessionDetail)
async def get_session_detail(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"},
        )
    messages = await repo.list_messages(db, session_id)
    triage = await repo.latest_triage(db, session_id)
    record = await repo.get_record_by_session(db, session_id)
    return SessionDetail(
        session=SessionOut.model_validate(session),
        messages=[MessageOut.model_validate(m) for m in messages],
        triage=_triage_dict(triage),
        has_record=record is not None,
    )


@router.patch("/{session_id}", response_model=SessionOut)
async def rename_session(
    session_id: UUID,
    req: SessionRenameRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    await repo.update_session(db, session, title=req.title)
    return SessionOut.model_validate(session)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    await repo.delete_session(db, session)
    return None


@router.get("/{session_id}/messages", response_model=list[MessageOut])
async def list_messages(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    messages = await repo.list_messages(db, session_id)
    return [MessageOut.model_validate(m) for m in messages]
