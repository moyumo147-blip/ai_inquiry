# backend/api/v1/auth.py

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import create_access_token, hash_password, verify_password
from backend.db import repositories as repo
from backend.db.session import get_db
from backend.dependencies import get_current_user
from backend.schemas.api import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册患者账号，成功后直接返回 token。"""
    if await repo.get_user_by_username(db, req.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "USERNAME_TAKEN", "message": "该用户名已被注册"},
        )

    user = await repo.create_user(
        db,
        username=req.username,
        password_hash=hash_password(req.password),
        display_name=req.display_name,
        age=req.age,
        gender=req.gender,
    )
    token = create_access_token(str(user.id), user.username, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await repo.get_user_by_username(db, req.username)
    if user is None or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "BAD_CREDENTIALS", "message": "用户名或密码错误"},
        )
    token = create_access_token(str(user.id), user.username, user.role)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(current_user: dict = Depends(get_current_user)):
    return current_user["user"]
