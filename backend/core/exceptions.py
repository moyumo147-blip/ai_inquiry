# backend/core/exceptions.py
# 统一业务异常：API 层捕获后转成 {code, message} 的 JSON 响应。

from fastapi import HTTPException, status


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "APP_ERROR"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code

    def to_http(self) -> HTTPException:
        return HTTPException(
            status_code=self.status_code,
            detail={"code": self.code, "message": self.message},
        )


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class AuthError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class LLMError(AppError):
    status_code = status.HTTP_502_BAD_GATEWAY
    code = "LLM_ERROR"


class RetrievalError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "RETRIEVAL_ERROR"
