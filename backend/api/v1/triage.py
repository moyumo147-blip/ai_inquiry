# backend/api/v1/triage.py

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.triage.graph import build_triage_graph
from backend.core import safety
from backend.db import repositories as repo
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import TriageRequest, TriageResponse

router = APIRouter(prefix="/triage", tags=["分诊"])


@router.post("", response_model=TriageResponse)
async def triage(
    req: TriageRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """根据主诉给出科室 + 紧急程度 + 追问清单，并落库。"""
    graph = build_triage_graph()
    state = await graph.ainvoke(
        {
            "chief_complaint": req.chief_complaint,
            "age": req.age if req.age is not None else current_user.get("age"),
            "gender": req.gender or current_user.get("gender"),
            "duration": req.duration,
        }
    )

    session_id: UUID | None = None
    if req.session_id:
        session = await repo.get_session(db, req.session_id, current_user["user_id"])
        if session is None:
            raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
        session_id = session.id
        await repo.update_session(
            db,
            session,
            department=state.get("department"),
            urgency=state.get("urgency"),
            chief_complaint=req.chief_complaint,
        )

    await repo.save_triage(
        db,
        user_id=current_user["user_id"],
        session_id=session_id,
        chief_complaint=req.chief_complaint,
        department=state.get("department"),
        urgency=state.get("urgency", "routine"),
        red_flags=state.get("red_flags") or [],
        differential=state.get("differential") or [],
        recommended_tests=state.get("recommended_tests") or [],
        questions=state.get("questions") or [],
        advice=state.get("advice"),
        safety_level=(state.get("safety") or {}).get("level"),
        raw={"rationale": state.get("rationale", ""), "fallback_used": state.get("fallback_used", False)},
    )

    return TriageResponse(
        department=state.get("department") or "全科医学科",
        urgency=state.get("urgency", "routine"),
        red_flags=state.get("red_flags") or [],
        differential=state.get("differential") or [],
        recommended_tests=state.get("recommended_tests") or [],
        questions=state.get("questions") or [],
        advice=state.get("advice") or "",
        rationale=state.get("rationale") or "",
        safety_level=(state.get("safety") or {}).get("level", "routine"),
        disclaimer=safety.DISCLAIMER,
    )


@router.get("/{session_id}")
async def get_triage(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    record = await repo.latest_triage(db, session_id)
    if record is None:
        return {"triage": None}
    return {
        "triage": {
            "department": record.department,
            "urgency": record.urgency,
            "red_flags": record.red_flags or [],
            "differential": record.differential or [],
            "recommended_tests": record.recommended_tests or [],
            "questions": record.questions or [],
            "advice": record.advice,
            "safety_level": record.safety_level,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
    }
