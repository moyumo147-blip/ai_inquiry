# backend/core/logger.py
# 轻量结构化日志：保留 EduAgent 的 logger.info("event", key=value) 调用风格，
# 但不引入 structlog 依赖（避免额外安装成本）。

import json
import logging
import sys

from backend.config import get_settings

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class StructuredLogger:
    """对标准 logging 的薄封装，支持事件名 + 关键字参数。"""

    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    @staticmethod
    def _format(event: str, fields: dict) -> str:
        if not fields:
            return event
        kv = " ".join(f"{k}={v}" for k, v in fields.items())
        return f"{event} | {kv}"

    def _log(self, level: int, event: str, fields: dict, exc_info: bool = False):
        self._logger.log(level, self._format(event, fields), exc_info=exc_info)

    def debug(self, event: str, **fields):
        self._log(logging.DEBUG, event, fields)

    def info(self, event: str, **fields):
        self._log(logging.INFO, event, fields)

    def warning(self, event: str, **fields):
        self._log(logging.WARNING, event, fields)

    def error(self, event: str, exc_info: bool = False, **fields):
        self._log(logging.ERROR, event, fields, exc_info=exc_info)

    def exception(self, event: str, **fields):
        self._log(logging.ERROR, event, fields, exc_info=True)


def configure_logging() -> None:
    """初始化根日志器（幂等，可在 main / 脚本中重复调用）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # 第三方库降噪
    for noisy in ("httpx", "httpcore", "openai", "asyncio", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> StructuredLogger:
    """获取结构化日志器。"""
    return StructuredLogger(name)
