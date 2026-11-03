# backend/core/embeddings.py
# 查询向量化：必须与知识库入库时使用的模型保持一致（DashScope text-embedding-v2，1536 维）。
# 知识库里的 54118 条 case_chunks.embedding 就是用这个模型生成的。

import asyncio
import hashlib
from functools import lru_cache

from openai import OpenAI

from backend.config import get_settings
from backend.core.exceptions import RetrievalError
from backend.core.logger import get_logger

logger = get_logger(__name__)

_BATCH_SIZE = 25  # DashScope text-embedding-v2 单次最多 25 条


class DashScopeEmbedder:
    """进程内单例封装（同步 SDK + 异步包装）。"""

    _instance: "DashScopeEmbedder | None" = None

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.dashscope_api_key:
            raise RetrievalError("未配置 DASHSCOPE_API_KEY，无法生成查询向量")
        self._client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base_url,
            timeout=60,
            max_retries=2,
        )
        self._model = settings.embedding_model

    @classmethod
    def get_instance(cls) -> "DashScopeEmbedder":
        if cls._instance is None:
            cls._instance = DashScopeEmbedder()
            logger.info("embedder.ready", model=cls._instance._model)
        return cls._instance

    # ── 同步接口 ──────────────────────────────────────────────
    def embed_query(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            raise RetrievalError("查询文本为空")
        return self._embed_cached(text)

    @lru_cache(maxsize=1024)
    def _embed_cached(self, text: str) -> list[float]:
        key = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
        try:
            resp = self._client.embeddings.create(input=text, model=self._model)
        except Exception as exc:  # 网络 / 额度 / 参数错误
            logger.error("embedder.failed", key=key, error=str(exc))
            raise RetrievalError(f"向量化失败：{exc}") from exc
        vector = resp.data[0].embedding
        logger.info("embedder.embedded", key=key, dims=len(vector))
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            resp = self._client.embeddings.create(input=batch, model=self._model)
            out.extend([d.embedding for d in resp.data])
        return out

    # ── 异步接口（业务代码用这个）────────────────────────────
    async def aembed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)


async def embed_query(text: str) -> list[float]:
    return await DashScopeEmbedder.get_instance().aembed_query(text)


def vector_literal(vector: list[float]) -> str:
    """转成 pgvector 可接受的字面量：'[0.1,0.2,...]'（配合 CAST(... AS vector)）。"""
    return "[" + ",".join(f"{x:.8f}" for x in vector) + "]"
