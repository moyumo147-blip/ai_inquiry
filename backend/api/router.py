# backend/api/router.py
# 聚合所有 v1 路由，main.py 只挂这一个。

from fastapi import APIRouter

from backend.api.v1 import auth, cases, chat, records, sessions, system, triage

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(sessions.router)
api_router.include_router(chat.router)
api_router.include_router(triage.router)
api_router.include_router(records.router)
api_router.include_router(cases.router)
api_router.include_router(system.router)
