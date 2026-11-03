# backend/api/v1/system.py

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.core.llm_factory import model_info
from backend.core.retriever import knowledge_stats
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import StatsOut

router = APIRouter(prefix="/system", tags=["系统"])


@router.get("/info")
async def info(current_user: dict = Depends(get_current_user)):
    settings = get_settings()
    return {
        "app": {"env": settings.app_env, "version": "1.0.0"},
        "models": model_info(),
        "retrieval": {
            "candidates": settings.retrieval_candidates,
            "top_k": settings.retrieval_top_k,
            "min_confidence": settings.min_confidence,
        },
    }


@router.get("/stats", response_model=StatsOut)
async def stats(
    current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    kb = await knowledge_stats(db)
    row = (
        await db.execute(
            text(
                """
                SELECT (SELECT count(*) FROM users)           AS users,
                       (SELECT count(*) FROM consult_sessions) AS sessions,
                       (SELECT count(*) FROM medical_records)  AS records
                """
            )
        )
    ).mappings().one()
    return StatsOut(**kb, users=int(row["users"]), sessions=int(row["sessions"]), records=int(row["records"]))
