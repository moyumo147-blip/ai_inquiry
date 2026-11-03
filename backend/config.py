# backend/config.py
# 全项目唯一的「配置中心」：从 .env.local 读取配置，供任何模块取用。
# 与 EduAgent 的 backend/config.py 保持同一套写法（pydantic-settings + lru_cache 单例）。

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env.local"


class Settings(BaseSettings):
    """配置模型：类属性 ↔ .env.local 中的配置项（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 数据库（PostgreSQL + pgvector，知识库已建好）──
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str = "postgres"
    db_password: str = "123456"

    @property
    def database_url(self) -> str:
        """SQLAlchemy 异步连接串（asyncpg 驱动）。"""
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── 大模型（阿里云百炼 DashScope，OpenAI 兼容接口）──
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    chat_model: str = "qwen-plus"          # 日常问诊 / 生成
    chat_model_strong: str = "qwen-max"    # 病历 / 分诊等需要稳定结构化的场景
    embedding_model: str = "text-embedding-v2"  # 必须与知识库入库时一致（1536 维）
    embedding_dim: int = 1536

    # ── JWT 认证 ──
    jwt_secret_key: str = "change-me-in-env-local"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 10080   # 7 天

    # ── 检索（RAG）──
    retrieval_candidates: int = 40     # 向量召回候选数
    retrieval_top_k: int = 6           # 精排后交给大模型的病例数
    qa_top_k: int = 3                  # 相似问答条数
    min_confidence: float = 0.35       # 低于该余弦相似度视为「知识库覆盖不足」

    # ── 长会话摘要 ──
    summary_trigger_messages: int = 12  # 消息数超过该值后触发摘要压缩
    summary_keep_recent: int = 6        # 压缩时保留最近 N 条原文，不进入摘要

    # ── 应用基础配置 ──
    app_env: str = "local"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache()
def get_settings() -> Settings:
    """全局唯一配置对象（首次调用读取 .env.local，之后复用缓存）。"""
    return Settings()
