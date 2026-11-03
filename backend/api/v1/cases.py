# backend/api/v1/cases.py
# 知识库病例的浏览与语义检索（只读，不写入知识库）。

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.retriever import (
    get_case_detail,
    list_departments,
    search_cases,
    search_cases_by_keyword,
)
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import CaseItem, CasePage

router = APIRouter(prefix="/cases", tags=["病例库"])


@router.get("", response_model=CasePage)
async def browse_cases(
    keyword: str = Query("", max_length=50),
    department: str = Query("", max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await search_cases_by_keyword(db, keyword, department, page, page_size)
    return CasePage(total=total, page=page, page_size=page_size, items=[CaseItem(**i) for i in items])


@router.get("/departments")
async def departments(
    limit: int = Query(30, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_departments(db, limit)


@router.get("/semantic")
async def semantic_search(
    q: str = Query(..., min_length=2, max_length=200),
    department: str | None = Query(None),
    top_k: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """向量检索：看知识库对某个问题能召回哪些病例（演示/调试用）。"""
    result = await search_cases(db, q, top_k=top_k, department=department)
    return {
        "query": q,
        "confidence": round(result.confidence, 4),
        "coverage": result.coverage,
        "cases": result.to_sources(),
    }


@router.get("/{case_id}")
async def case_detail(
    case_id: int,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await get_case_detail(db, case_id)
    if data is None:
        raise HTTPException(status_code=404, detail={"code": "CASE_NOT_FOUND", "message": "病例不存在"})
    if data.get("created_at") is not None:
        data["created_at"] = data["created_at"].isoformat()
    return data
