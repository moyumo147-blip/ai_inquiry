# backend/core/llm_factory.py
# LLM 工厂：所有 Agent 必须通过这里拿模型，禁止在业务代码里直接 new ChatOpenAI。
# 与 EduAgent 的 core/llm_factory.py 同一职责，只是把 DeepSeek 换成了阿里云百炼（DashScope）。

from typing import Any, Type

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

# 绕过系统代理：Windows 上 HTTPS_PROXY 常导致 TLS 握手失败（沿用 EduAgent 的处理）
_HTTP_ASYNC_CLIENT = httpx.AsyncClient(
    trust_env=False,
    timeout=httpx.Timeout(180.0, connect=15.0),
)

# 业务类型 → (模型档位, 默认温度)
_AGENT_ROUTING: dict[str, tuple[str, float]] = {
    "consultation": ("chat", 0.4),      # 问诊对话：需要一点表达自然度
    "consultation_followup": ("chat", 0.5),
    "triage": ("strong", 0.1),          # 分诊：结构化、要稳
    "record": ("strong", 0.1),          # 病历：结构化、要稳
    "intent": ("chat", 0.0),            # 意图识别
    "summary": ("chat", 0.2),           # 会话摘要
    "safety": ("strong", 0.0),          # 安全复核
}


class LLMFactory:
    """模型实例缓存工厂。"""

    _instances: dict[str, BaseChatModel] = {}

    @classmethod
    def _model_name(cls, tier: str) -> str:
        settings = get_settings()
        return settings.chat_model_strong if tier == "strong" else settings.chat_model

    @classmethod
    def get_llm(
        cls,
        agent_type: str,
        temperature: float | None = None,
        streaming: bool = False,
    ) -> BaseChatModel:
        if agent_type not in _AGENT_ROUTING:
            raise ValueError(
                f"未知 agent_type: '{agent_type}'，可用：{list(_AGENT_ROUTING.keys())}"
            )
        settings = get_settings()
        tier, default_temp = _AGENT_ROUTING[agent_type]
        temp = default_temp if temperature is None else temperature
        model = cls._model_name(tier)

        cache_key = f"{model}|{temp}|{streaming}"
        if cache_key not in cls._instances:
            cls._instances[cache_key] = ChatOpenAI(
                model=model,
                api_key=settings.dashscope_api_key,  # type: ignore[arg-type]
                base_url=settings.dashscope_base_url,
                temperature=temp,
                streaming=streaming,
                max_retries=0,
                timeout=180,
                http_async_client=_HTTP_ASYNC_CLIENT,
            )
            logger.info(
                "llm_factory.model_created",
                agent_type=agent_type,
                model=model,
                temperature=temp,
                streaming=streaming,
            )
        return cls._instances[cache_key]

    @classmethod
    def get_structured_llm(
        cls,
        agent_type: str,
        schema: Type[BaseModel],
        temperature: float | None = None,
    ) -> Runnable:
        llm = cls.get_llm(agent_type, temperature=temperature, streaming=False)
        return llm.with_structured_output(schema, method="function_calling")

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances.clear()
        logger.info("llm_factory.cache_cleared")


def get_llm(agent_type: str, temperature: float | None = None, streaming: bool = False) -> BaseChatModel:
    return LLMFactory.get_llm(agent_type, temperature=temperature, streaming=streaming)


def get_structured_llm(
    agent_type: str, schema: Type[BaseModel], temperature: float | None = None
) -> Runnable:
    return LLMFactory.get_structured_llm(agent_type, schema, temperature=temperature)


def model_info() -> dict[str, Any]:
    """给 /health、/system/info 用的模型信息。"""
    settings = get_settings()
    return {
        "chat_model": settings.chat_model,
        "chat_model_strong": settings.chat_model_strong,
        "embedding_model": settings.embedding_model,
        "embedding_dim": settings.embedding_dim,
    }
