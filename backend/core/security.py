# backend/core/security.py
# 密码哈希（PBKDF2-SHA256，标准库实现，零额外依赖）+ JWT 签发/校验。

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from backend.config import get_settings
from backend.core.exceptions import AuthError

_ITERATIONS = 200_000
_ALGO = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """生成 `pbkdf2_sha256$iterations$salt_hex$hash_hex` 格式的密码串。"""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
        if algo != _ALGO:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def create_access_token(user_id: str, username: str, role: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:  # 过期 / 签名错误 / 格式错误
        raise AuthError(f"登录状态无效或已过期：{exc}") from exc
