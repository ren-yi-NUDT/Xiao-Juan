# -*- coding: utf-8 -*-
"""管理端登录令牌：HMAC 签名的轻量 token，不引入额外依赖。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from fastapi import Header, HTTPException

from app.config import get_config


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    secret = get_config().app.secret.encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()[:32]


def make_token(user: str) -> str:
    hours = int(getattr(get_config().app, "token_hours", 12))
    payload = json.dumps(
        {"u": user, "exp": int(time.time()) + hours * 3600},
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{_b64encode(payload)}.{_sign(payload)}"


def verify_token(token: str) -> str | None:
    try:
        encoded, signature = token.split(".", 1)
        payload = _b64decode(encoded)
        if not hmac.compare_digest(_sign(payload), signature):
            return None
        data = json.loads(payload.decode("utf-8"))
        if int(data.get("exp", 0)) < time.time():
            return None
        return str(data.get("u") or "")
    except Exception:
        return None


async def require_admin(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    user = verify_token(authorization.split(" ", 1)[1].strip())
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return user
