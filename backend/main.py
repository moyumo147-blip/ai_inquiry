# backend/main.py
# FastAPI 入口：日志 → 迁移 → 路由 → 健康检查。

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api.router import api_router
from backend.config import get_settings
from backend.core.exceptions import AppError
from backend.core.llm_factory import LLMFactory
from backend.core.logger import configure_logging, get_logger
from backend.db.migrations import run_migrations
from backend.db.session import dispose_engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger(__name__)
    logger.info("app.starting", env=settings.app_env, port=settings.app_port)

    try:
        await run_migrations()
    except Exception as exc:  # 迁移失败只告警，不阻断启动
        logger.warning("app.migrations_failed", error=str(exc)[:300])

    logger.info("app.started", docs="/docs")
    yield

    logger.info("app.shutting_down")
    await dispose_engine()
    LLMFactory.clear_cache()
    logger.info("app.shutdown_complete")


app = FastAPI(
    title="AI 问诊系统 API",
    description=(
        "基于 54118 条真实医患病例构建的 AI 预问诊系统：分诊 → 问诊（RAG）→ 病历生成。"
        "\n\n仅用于健康科普与就医方向参考，不能替代执业医师诊断。"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": {"code": exc.code, "message": exc.message}},
    )


@app.get("/health", tags=["系统"])
async def health():
    return {"status": "ok", "env": settings.app_env, "service": "ai-consultation"}
