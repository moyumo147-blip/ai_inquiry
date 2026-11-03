# backend/api/v1/records.py

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.record.graph import build_record_graph
from backend.core.logger import get_logger
from backend.db import repositories as repo
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import RecordGenerateRequest, RecordOut, RecordUpdateRequest

router = APIRouter(prefix="/records", tags=["病历"])
logger = get_logger(__name__)

_SOAP_FIELDS = [
    "chief_complaint",
    "present_illness",
    "past_history",
    "allergy_history",
    "physical_exam",
    "assessment",
    "plan",
    "diagnosis",
]


@router.post("/generate", response_model=RecordOut)
async def generate_record(
    req: RecordGenerateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """基于会话对话生成 SOAP 病历（已存在则覆盖为新的草稿）。"""
    session = await repo.get_session(db, req.session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})

    messages = await repo.list_messages(db, session.id)
    if len(messages) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "NOT_ENOUGH_DIALOGUE", "message": "对话内容太少，先完成一轮问诊再生成病历"},
        )

    triage_record = await repo.latest_triage(db, session.id)
    triage = (
        {
            "department": triage_record.department,
            "urgency": triage_record.urgency,
            "red_flags": triage_record.red_flags or [],
        }
        if triage_record
        else None
    )

    graph = build_record_graph()
    state = await graph.ainvoke(
        {
            "session_id": str(session.id),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "triage": triage,
        }
    )
    soap: dict = state.get("soap") or {}

    data = {field: soap.get(field) for field in _SOAP_FIELDS}
    data["soap"] = soap
    data["status"] = "draft"

    record = await repo.upsert_record(db, session.id, current_user["user_id"], data)
    logger.info("records.generated", session_id=str(session.id), fallback=state.get("fallback_used"))
    return RecordOut.model_validate(record)


@router.get("", response_model=list[RecordOut])
async def list_records(
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    records = await repo.list_records(db, current_user["user_id"])
    return [RecordOut.model_validate(r) for r in records]


@router.get("/by-session/{session_id}", response_model=RecordOut)
async def get_record_by_session(
    session_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = await repo.get_session(db, session_id, current_user["user_id"])
    if session is None:
        raise HTTPException(status_code=404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    record = await repo.get_record_by_session(db, session_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "RECORD_NOT_FOUND", "message": "该会话还没有病历"})
    return RecordOut.model_validate(record)


@router.get("/{record_id}", response_model=RecordOut)
async def get_record(
    record_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await repo.get_record(db, record_id)
    if record is None or str(record.user_id) != current_user["user_id"]:
        raise HTTPException(status_code=404, detail={"code": "RECORD_NOT_FOUND", "message": "病历不存在"})
    return RecordOut.model_validate(record)


@router.put("/{record_id}", response_model=RecordOut)
async def update_record(
    record_id: int,
    req: RecordUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await repo.get_record(db, record_id)
    if record is None or str(record.user_id) != current_user["user_id"]:
        raise HTTPException(status_code=404, detail={"code": "RECORD_NOT_FOUND", "message": "病历不存在"})

    data = req.model_dump(exclude_none=True)
    if data:
        soap = dict(record.soap or {})
        soap.update(data)
        data["soap"] = soap
    updated = await repo.upsert_record(db, record.session_id, current_user["user_id"], data)
    return RecordOut.model_validate(updated)
