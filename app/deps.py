"""FastAPI 依赖：数据库、认证用户与 RBAC。"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.config import get_settings
from app.db import Database
from app.security import decode_token


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_current_user(
    request: Request,
    db: Database = Depends(get_db),
) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    payload = decode_token(auth[7:], get_settings())
    user = db.get_user_by_username(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user["status"] in ("banned", "muted"):
        raise HTTPException(status_code=403, detail="账号状态异常")
    return user


def require_role(*roles: str):
    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return user

    return dependency


async def get_optional_user(
    request: Request,
    db: Database = Depends(get_db),
) -> dict | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth[7:], get_settings())
        user = db.get_user_by_username(payload["sub"])
        if user and user["status"] in ("active",):
            return user
    except Exception:
        return None
    return None

