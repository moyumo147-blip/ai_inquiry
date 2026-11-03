# backend/dependencies.py
# FastAPI 依赖：数据库会话（见 db/session.py）+ JWT 当前用户。

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import AuthError
from backend.core.security import decode_access_token
from backend.db import repositories as repo
from backend.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """校验 Authorization: Bearer <token>，返回当前用户信息。"""
    if credentials is None or not credentials.credentials:
        raise AuthError("未登录或缺少访问令牌").to_http()

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("令牌缺少用户标识").to_http()

    user = await repo.get_user(db, user_id)
    if user is None:
        raise AuthError("用户不存在或已被删除").to_http()

    return {
        "user_id": str(user.id),
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "age": user.age,
        "gender": user.gender,
        "user": user,
    }
