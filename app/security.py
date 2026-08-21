"""密码哈希、签名 Token 与 RBAC 校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import time
import urllib.parse

from fastapi import HTTPException

from app.config import Settings, get_settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), 120_000
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def create_token(
    username: str, role: str, settings: Settings, ttl_seconds: int | None = None
) -> str:
    ttl = (
        ttl_seconds
        if ttl_seconds is not None
        else settings.token_ttl_hours * 3600
    )
    payload = {
        "sub": username,
        "role": role,
        "exp": int(time.time()) + ttl,
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(
        settings.secret_key.encode(), body.encode(), hashlib.sha256
    ).digest()
    return f"{body}.{_b64(signature)}"


def decode_token(token: str, settings: Settings) -> dict:
    try:
        body, sig = token.split(".", 1)
        expected = hmac.new(
            settings.secret_key.encode(), body.encode(), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            raise ValueError("signature mismatch")
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            raise ValueError("expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已过期") from exc


_WEAK_PASSWORDS = {
    "12345678",
    "123456789",
    "1234567890",
    "password",
    "password1",
    "qwerty123",
    "admin123",
    "demo123",
    "11111111",
    "88888888",
    "abcdefg1",
}


def validate_password_policy(username: str, password: str) -> None:
    if len(password) < 8 or len(password) > 64:
        raise ValueError("密码长度需为 8-64 位")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("密码必须同时包含字母和数字")
    lowered = password.lower()
    if username and username.lower() in lowered:
        raise ValueError("密码不能包含用户名")
    if lowered in _WEAK_PASSWORDS:
        raise ValueError("密码过于常见，请更换")


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def create_access_token(username: str, role: str, settings: Settings) -> str:
    return create_token(
        username, role, settings, ttl_seconds=settings.access_token_ttl_minutes * 60
    )


def create_refresh_token() -> tuple[str, str]:
    token = os.urandom(32).hex()
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def totp_uri(secret: str, username: str, issuer: str) -> str:
    label = urllib.parse.quote(f"{issuer}:{username}")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={urllib.parse.quote(issuer)}"
    )


def totp_code(secret: str, offset: int = 0) -> str:
    normalized = secret.replace(" ", "").upper()
    key = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
    counter = int(time.time()) // 30 + offset
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    pos = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[pos : pos + 4])[0] & 0x7FFFFFFF
    return f"{value % 1000000:06d}"


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    if not re.fullmatch(r"\d{6}", code.strip()):
        return False
    normalized = secret.replace(" ", "").upper()
    try:
        key = base64.b32decode(normalized + "=" * (-len(normalized) % 8))
    except Exception:
        return False
    for offset in range(-window, window + 1):
        counter = int(time.time()) // 30 + offset
        digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
        pos = digest[-1] & 0x0F
        value = struct.unpack(">I", digest[pos : pos + 4])[0] & 0x7FFFFFFF
        if f"{value % 1000000:06d}" == code.strip():
            return True
    return False

