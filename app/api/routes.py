"""全部业务 API：认证、对话、行程、社区、审核与运营指标。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.agent.multi_graph import create_agent
from app.config import get_settings
from app.db import Database
from app.deps import (
    get_current_user,
    get_db,
    get_optional_user,
    require_role,
    require_verified,
)
from app.eval.runner import run_demo_eval
from app.llm import get_llm
from app.observability.audit import audit
from app.observability.metrics import metrics
from app.rag.search import HybridSearcher
from app.schemas import (
    ChangePasswordRequest,
    ChatRequest,
    CommentCreate,
    DepartureDateUpdate,
    FollowUpdate,
    ForgotPasswordRequest,
    GuideCreate,
    LoginRequest,
    ProfileUpdate,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ReviewDecision,
    SendCodeRequest,
    TotpEnableRequest,
    TotpRequest,
    VerifyPhoneRequest,
)
from app.sms import send_sms_code
from app.security import (
    create_access_token,
    create_refresh_token,
    generate_totp_secret,
    generate_verification_code,
    hash_password,
    hash_token,
    totp_uri,
    validate_password_policy,
    verify_password,
    verify_totp,
)
from app.services.planner import _recompute_costs, build_itinerary
from app.services.price_enrich import enrich_plan_with_prices

router = APIRouter()

_rate_buckets: dict[str, deque[float]] = {}
_SEARCHER = HybridSearcher()


def _rate_limit(key: str) -> None:
    settings = get_settings()
    now = time.time()
    bucket = _rate_buckets.setdefault(key, deque())
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    if len(bucket) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    bucket.append(now)


_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _rate_limit_window(key: str, limit: int, window_seconds: int) -> None:
    now = time.time()
    bucket = _rate_buckets.setdefault(key, deque())
    while bucket and bucket[0] < now - window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
    bucket.append(now)


def _is_locked(user: dict) -> bool:
    locked = user.get("locked_until") or ""
    if not locked:
        return False
    try:
        return datetime.fromisoformat(locked) > datetime.now(timezone.utc)
    except Exception:
        return False


async def _sync_weather(
    itinerary: dict[str, Any],
    city: str = "",
    departure_date: str = "",
    days: int = 1,
) -> None:
    """按当前出发日期刷新真实天气；预报范围外明确提示，不残留旧数据。"""
    for key in (
        "weather",
        "weather_advice",
        "weather_warnings",
        "weather_unavailable",
        "weather_notice",
        "weather_max_days",
        "weather_missing",
    ):
        itinerary.pop(key, None)
    if not city or not departure_date:
        itinerary["weather_unavailable"] = True
        itinerary["weather_notice"] = "尚未设置出发日期，无法查询当天天气。"
        return
    from app.tools.weather import (
        WeatherService,
        travel_advice,
        weather_unavailable_notice,
    )

    weather_service = WeatherService()
    max_days = weather_service.max_forecast_days()
    itinerary["weather_max_days"] = max_days
    weather = await weather_service.forecast(city, None, None, departure_date, days)
    warnings = await weather_service.warnings(city, None, None)
    missing: list[dict[str, Any]] = []
    try:
        start = date.fromisoformat(departure_date)
        for i in range(max(1, int(days))):
            day_iso = (start + timedelta(days=i)).isoformat()
            if not any(str(w.get("date", "")) == day_iso for w in weather):
                missing.append(
                    {
                        "date": day_iso,
                        "reason": weather_unavailable_notice(day_iso, max_days),
                    }
                )
    except (TypeError, ValueError):
        missing = []
    if missing:
        itinerary["weather_missing"] = missing
    else:
        itinerary.pop("weather_missing", None)
    if weather:
        itinerary["weather"] = weather
        itinerary["weather_advice"] = travel_advice(weather)
        if warnings:
            itinerary["weather_warnings"] = warnings
    else:
        itinerary["weather_unavailable"] = True
        itinerary["weather_notice"] = weather_unavailable_notice(
            departure_date, weather_service.max_forecast_days()
        )


@router.post("/auth/send-code")
async def send_code(
    req: SendCodeRequest,
    request: Request,
    db: Database = Depends(get_db),
):
    settings = get_settings()
    phone = req.phone.strip()
    purpose = req.purpose.strip()
    if purpose not in ("register", "reset", "verify"):
        raise HTTPException(status_code=400, detail="无效的验证码用途")
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    _rate_limit_window(f"phone_code:{phone}", settings.phone_code_per_minute, 60)
    _rate_limit_window(f"phone_code_ip:{_client_ip(request)}", 10, 3600)
    code = generate_verification_code()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(
        timespec="seconds"
    )
    db.save_verification_code(phone, purpose, code, expires)
    sent = send_sms_code(phone, code, purpose)
    audit(db, None, "send_code", "phone", phone, purpose)
    return {"status": "ok", "sms_sent": sent}


@router.post("/auth/register")
async def register(
    req: RegisterRequest,
    request: Request,
    db: Database = Depends(get_db),
):
    settings = get_settings()
    _rate_limit_window(
        f"register:{_client_ip(request)}", settings.phone_register_per_hour, 3600
    )
    username = req.username.strip()
    phone = req.phone.strip()
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    if db.get_user_by_username(username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if db.get_user_by_phone(phone):
        raise HTTPException(status_code=409, detail="手机号已注册")
    try:
        validate_password_policy(username, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = db.get_verification_code(phone, "register")
    if (
        not row
        or row["code"] != req.code.strip()
        or row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds")
    ):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    user_id = db.create_user(username, req.password, phone=phone, phone_verified=1)
    db.mark_code_used(row["id"])
    audit(db, user_id, "register", detail=username)
    db.record_login_audit(
        username,
        True,
        _client_ip(request),
        request.headers.get("user-agent", ""),
        "register",
    )
    return {"status": "ok"}


@router.post("/auth/verify-phone")
async def verify_phone(
    req: VerifyPhoneRequest,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    phone = user.get("phone") or ""
    if not phone:
        raise HTTPException(status_code=400, detail="请先绑定手机号")
    if user.get("phone_verified"):
        return {"status": "ok"}
    row = db.get_verification_code(phone, "verify")
    if (
        not row
        or row["code"] != req.code.strip()
        or row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds")
    ):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    db.set_phone_verified(user["id"])
    db.mark_code_used(row["id"])
    audit(db, user["id"], "verify_phone", "phone", phone)
    return {"status": "ok"}


@router.post("/auth/login")
async def login(
    req: LoginRequest,
    request: Request,
    db: Database = Depends(get_db),
):
    settings = get_settings()
    ip = _client_ip(request)
    ua = request.headers.get("user-agent", "")
    _rate_limit_window(f"login_ip:{ip}", settings.auth_login_per_minute, 60)
    _rate_limit_window(
        f"login_user:{req.username.strip().lower()}",
        settings.auth_login_per_hour,
        3600,
    )
    user = db.get_user_by_username(req.username.strip())
    if user and _is_locked(user):
        db.record_login_audit(req.username, False, ip, ua, "locked")
        raise HTTPException(status_code=423, detail="账号已锁定，请稍后再试")
    if not user or not verify_password(req.password, user["password_hash"]):
        if user:
            db.record_login_failure(user["username"])
        db.record_login_audit(req.username, False, ip, ua, "bad_password")
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user["status"] == "banned":
        db.record_login_audit(req.username, False, ip, ua, "banned")
        raise HTTPException(status_code=403, detail="账号已被封禁")
    if user.get("totp_secret") and (
        not req.totp_code or not verify_totp(user["totp_secret"], req.totp_code)
    ):
        db.record_login_audit(req.username, False, ip, ua, "bad_totp")
        raise HTTPException(status_code=401, detail="动态验证码错误")
    db.reset_login_failures(user["id"])
    db.set_last_login(user["id"], ip)
    db.record_login_audit(req.username, True, ip, ua, "login")
    access_token = create_access_token(user["username"], user["role"], settings)
    refresh_plain, refresh_hash = create_refresh_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)).isoformat(
        timespec="seconds"
    )
    db.create_refresh_token(user["id"], refresh_hash, expires)
    audit(db, user["id"], "login")
    return {
        "access_token": access_token,
        "refresh_token": refresh_plain,
        "token_type": "bearer",
        "email_verified": bool(user.get("email_verified")),
        "phone_verified": bool(user.get("phone_verified")),
        "must_change_password": bool(user.get("must_change_password")),
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
            "phone": user.get("phone") or "",
        },
    }


@router.post("/auth/refresh")
async def refresh_token(
    req: RefreshRequest,
    db: Database = Depends(get_db),
):
    row = db.get_refresh_token(hash_token(req.refresh_token))
    if not row or row["expires_at"] < datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ):
        raise HTTPException(status_code=401, detail="登录已过期")
    user = db.get_user_by_id(row["user_id"])
    if not user or user["status"] == "banned":
        raise HTTPException(status_code=401, detail="账号不可用")
    settings = get_settings()
    access_token = create_access_token(user["username"], user["role"], settings)
    db.revoke_refresh_token(row["token_hash"])
    refresh_plain, refresh_hash = create_refresh_token()
    expires = (datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_ttl_days)).isoformat(
        timespec="seconds"
    )
    db.create_refresh_token(user["id"], refresh_hash, expires)
    return {
        "access_token": access_token,
        "refresh_token": refresh_plain,
        "token_type": "bearer",
    }


@router.post("/auth/logout")
async def logout(
    req: RefreshRequest,
    db: Database = Depends(get_db),
):
    db.revoke_refresh_token(hash_token(req.refresh_token))
    return {"status": "ok"}


@router.post("/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not verify_password(req.old_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="原密码错误")
    try:
        validate_password_policy(user["username"], req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.update_password(user["id"], hash_password(req.new_password))
    db.revoke_all_user_refresh_tokens(user["id"])
    audit(db, user["id"], "change_password")
    return {"status": "ok"}


@router.post("/auth/forgot-password")
async def forgot_password(
    req: ForgotPasswordRequest,
    request: Request,
    db: Database = Depends(get_db),
):
    settings = get_settings()
    _rate_limit_window(f"forgot:{_client_ip(request)}", 3, 3600)
    phone = req.phone.strip()
    if not _PHONE_RE.match(phone):
        raise HTTPException(status_code=400, detail="手机号格式不正确")
    user = db.get_user_by_phone(phone)
    if user:
        code = generate_verification_code()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(
            timespec="seconds"
        )
        db.save_verification_code(phone, "reset", code, expires)
        send_sms_code(phone, code, "reset")
        db.record_login_audit(
            user["username"],
            True,
            _client_ip(request),
            request.headers.get("user-agent", ""),
            "forgot_password",
        )
    return {"status": "ok"}


@router.post("/auth/reset-password")
async def reset_password(
    req: ResetPasswordRequest,
    db: Database = Depends(get_db),
):
    phone = req.phone.strip()
    user = db.get_user_by_phone(phone)
    if not user:
        raise HTTPException(status_code=400, detail="用户不存在")
    row = db.get_verification_code(phone, "reset")
    if (
        not row
        or row["code"] != req.code.strip()
        or row["expires_at"] < datetime.now(timezone.utc).isoformat(timespec="seconds")
    ):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    try:
        validate_password_policy(user["username"], req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.update_password(user["id"], hash_password(req.new_password))
    db.mark_code_used(row["id"])
    db.revoke_all_user_refresh_tokens(user["id"])
    audit(db, user["id"], "reset_password")
    return {"status": "ok"}


@router.get("/auth/2fa/setup")
async def twofa_setup(
    user: dict = Depends(get_current_user),
):
    if user.get("totp_secret"):
        raise HTTPException(status_code=400, detail="已绑定动态口令")
    secret = generate_totp_secret()
    return {
        "secret": secret,
        "uri": totp_uri(secret, user["username"], get_settings().totp_issuer),
    }


@router.post("/auth/2fa/enable")
async def twofa_enable(
    req: TotpEnableRequest,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if user.get("totp_secret"):
        raise HTTPException(status_code=400, detail="已绑定动态口令")
    if not verify_totp(req.secret, req.code):
        raise HTTPException(status_code=400, detail="动态验证码错误")
    db.set_totp_secret(user["id"], req.secret.strip().upper())
    audit(db, user["id"], "enable_2fa")
    return {"status": "ok"}


@router.post("/auth/2fa/disable")
async def twofa_disable(
    req: TotpRequest,
    db: Database = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    if not user.get("totp_secret"):
        raise HTTPException(status_code=400, detail="未绑定动态口令")
    if not verify_totp(user["totp_secret"], req.code):
        raise HTTPException(status_code=400, detail="动态验证码错误")
    db.set_totp_secret(user["id"], "")
    audit(db, user["id"], "disable_2fa")
    return {"status": "ok"}


@router.get("/profile/me")
async def my_profile(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user", "admin", "super_admin")),
):
    profile = db.get_user_profile(user["id"], user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@router.put("/profile/me")
async def update_profile(
    req: ProfileUpdate,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user", "admin", "super_admin")),
):
    db.update_user_profile(
        user["id"], req.nickname.strip(), req.avatar.strip()
    )
    return db.get_user_profile(user["id"], user["id"])


@router.post("/profile/me/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user", "admin", "super_admin")),
):
    if file.content_type and not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="仅支持图片")
    settings = get_settings()
    upload_dir = Path(settings.db_dir) / "uploads" / "avatars" / str(user["id"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()[:10] or ".jpg"
    filename = f"{uuid.uuid4().hex[:10]}{suffix}"
    (upload_dir / filename).write_bytes(await file.read())
    avatar = f"/uploads/avatars/{user['id']}/{filename}"
    db.update_user_profile(user["id"], avatar=avatar)
    return {"avatar": avatar}


@router.get("/users/{user_id}/profile")
async def user_profile(
    user_id: int,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    profile = db.get_user_profile(user_id, user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@router.post("/users/{user_id}/follow")
async def follow_user(
    user_id: int,
    req: FollowUpdate,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能关注自己")
    db.follow_user(user["id"], user_id, req.follow)
    return db.get_user_profile(user_id, user["id"])


@router.post("/chat")
async def chat(
    req: ChatRequest,
    db: Database = Depends(get_db),
    user: dict = Depends(require_verified),
    stream: bool = False,
):
    _rate_limit(f"chat:{user['id']}")
    metrics.record_request()
    t0 = time.perf_counter()

    llm = get_llm()
    agent = create_agent(db, llm, _SEARCHER)

    session_id = req.session_id or uuid.uuid4().hex[:12]
    run_id = uuid.uuid4().hex[:12]
    prompt_before = metrics.prompt_tokens
    completion_before = metrics.completion_tokens
    conv = db.get_conversation(session_id, user["id"])
    history = json.loads(conv["messages"]) if conv else []
    history.append({"role": "user", "content": req.message})
    effective_trip_id = req.trip_id or ""

    if stream:
        from fastapi.responses import StreamingResponse

        state_input = {
            "user_input": req.message,
            "user_id": user["id"],
            "trip_id": effective_trip_id,
            "history": history,
        }
        config = {"recursion_limit": 50}
        db.start_agent_run(run_id, user["id"], session_id, req.message)
        events: asyncio.Queue = asyncio.Queue()

        async def run_agent_task() -> None:
            final_state: dict[str, Any] = {}
            try:
                async for mode, data in agent.astream(
                    state_input,
                    config=config,
                    stream_mode=["custom", "values"],
                ):
                    if (
                        mode == "custom"
                        and isinstance(data, dict)
                        and data.get("type") in ("stage", "day")
                    ):
                        await events.put(data)
                    elif mode == "values":
                        final_state = data

                plan = final_state.get("itinerary", {})
                plan = enrich_plan_with_prices(plan, db)
                plan = _recompute_costs(plan)
                _params = final_state.get("params") or plan.get("params") or {}
                await _sync_weather(
                    plan,
                    plan.get("city") or _params.get("city", ""),
                    _params.get("departure_date", ""),
                    max(
                        1,
                        len(plan.get("days") or [])
                        or int(_params.get("days", 1) or 1),
                    ),
                )
                response = final_state.get("response", "") or ""
                trip_id = final_state.get("trip_id", effective_trip_id)
                if trip_id:
                    db.update_trip(
                        trip_id,
                        final_state.get("version", 1),
                        final_state.get("params", {}),
                        plan,
                    )
                    db.set_last_trip_id(session_id, user["id"], trip_id)
                history.append({"role": "assistant", "content": response})
                db.upsert_conversation(session_id, user["id"], history)
                elapsed = int((time.perf_counter() - t0) * 1000)
                metrics.record_success(elapsed, final_state.get("intent", "chat"))
                db.save_agent_run(
                    run_id,
                    user["id"],
                    session_id,
                    final_state.get("intent", "chat"),
                    "success",
                    req.message,
                    plan,
                    response,
                    final_state.get("agent_results") or [],
                    final_state.get("tool_calls") or [],
                    max(0, metrics.prompt_tokens - prompt_before),
                    max(0, metrics.completion_tokens - completion_before),
                    elapsed,
                )
                for i in range(0, len(response), 6):
                    await events.put({"token": response[i:i + 6]})
                await events.put(
                    {
                        "done": True,
                        "run_id": run_id,
                        "session_id": session_id,
                        "trip_id": trip_id,
                        "itinerary": plan,
                        "version": final_state.get("version", 1),
                        "validation_issues": plan.get("validation_issues", []),
                        "agents": sorted(
                            {
                                r.get("agent")
                                for r in (final_state.get("agent_results") or [])
                                if r.get("status") == "success"
                            }
                        ),
                        "elapsed_ms": elapsed,
                    }
                )
            except Exception as exc:
                elapsed = int((time.perf_counter() - t0) * 1000)
                metrics.record_failure(elapsed, "agent_error")
                db.save_agent_run(
                    run_id,
                    user["id"],
                    session_id,
                    final_state.get("intent", "chat") or "unknown",
                    "failed",
                    req.message,
                    final_state.get("itinerary") or {},
                    final_state.get("response") or "",
                    final_state.get("agent_results") or [],
                    final_state.get("tool_calls") or [],
                    max(0, metrics.prompt_tokens - prompt_before),
                    max(0, metrics.completion_tokens - completion_before),
                    elapsed,
                    str(exc),
                )
                await events.put({"error": str(exc)})
            finally:
                await events.put(None)

        asyncio.create_task(run_agent_task())

        async def event_generator():
            while True:
                item = await events.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    db.start_agent_run(run_id, user["id"], session_id, req.message)
    try:
        state = await agent.ainvoke(
            {
                "user_input": req.message,
                "user_id": user["id"],
                "trip_id": effective_trip_id,
                "history": history,
            }
        )
        plan = state.get("itinerary", {})
        plan = enrich_plan_with_prices(plan, db)
        plan = _recompute_costs(plan)
        _params = state.get("params") or plan.get("params") or {}
        await _sync_weather(
            plan,
            plan.get("city") or _params.get("city", ""),
            _params.get("departure_date", ""),
            max(
                1,
                len(plan.get("days") or []) or int(_params.get("days", 1) or 1),
            ),
        )
        response = state.get("response", "")
        trip_id = state.get("trip_id", effective_trip_id)
        if trip_id:
            db.update_trip(
                trip_id,
                state.get("version", 1),
                state.get("params", {}),
                plan,
            )
            db.set_last_trip_id(session_id, user["id"], trip_id)
        history.append({"role": "assistant", "content": response})
        db.upsert_conversation(session_id, user["id"], history)
        elapsed = int((time.perf_counter() - t0) * 1000)
        metrics.record_success(elapsed, state.get("intent", "chat"))
        db.save_agent_run(
            run_id,
            user["id"],
            session_id,
            state.get("intent", "chat"),
            "success",
            req.message,
            plan,
            response,
            state.get("agent_results") or [],
            state.get("tool_calls") or [],
            max(0, metrics.prompt_tokens - prompt_before),
            max(0, metrics.completion_tokens - completion_before),
            elapsed,
        )
        return {
            "run_id": run_id,
            "session_id": session_id,
            "trip_id": trip_id,
            "intent": state.get("intent", "chat"),
            "response": response,
            "itinerary": plan,
            "version": state.get("version", 1),
            "validation_issues": plan.get("validation_issues", []),
            "agents": sorted(
                {
                    r.get("agent")
                    for r in (state.get("agent_results") or [])
                    if r.get("status") == "success"
                }
            ),
            "elapsed_ms": elapsed,
        }
    except Exception as exc:
        elapsed = int((time.perf_counter() - t0) * 1000)
        metrics.record_failure(elapsed, "agent_error")
        db.save_agent_run(
            run_id,
            user["id"],
            session_id,
            "unknown",
            "failed",
            req.message,
            {},
            "",
            [],
            [],
            max(0, metrics.prompt_tokens - prompt_before),
            max(0, metrics.completion_tokens - completion_before),
            elapsed,
            str(exc),
        )
        audit(db, user["id"], "chat_failed", detail=str(exc))
        raise HTTPException(status_code=500, detail=f"规划失败：{exc}") from exc


@router.get("/chat/status")
async def chat_status(
    session_id: str = "",
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user", "admin", "super_admin")),
):
    if not session_id:
        return {"status": "", "run_id": ""}
    row = db.query_one(
        "SELECT run_id, status, user_input FROM agent_runs "
        "WHERE session_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT 1",
        (session_id, user["id"]),
    )
    if not row:
        return {"status": "", "run_id": ""}
    return {
        "run_id": row["run_id"],
        "status": row["status"],
        "user_input": (row["user_input"] or "")[:200],
    }


@router.get("/conversation")
async def get_conversation(
    session_id: str = "",
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    if not session_id:
        return {"messages": [], "last_trip_id": ""}
    conv = db.get_conversation(session_id, user["id"])
    if not conv:
        return {"messages": [], "last_trip_id": ""}
    return {
        "messages": json.loads(conv.get("messages") or "[]"),
        "last_trip_id": conv.get("last_trip_id", ""),
    }


@router.get("/trips")
async def list_trips(
    page: int = 1,
    page_size: int = 6,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    data = db.paginate_trips(user["id"], page=page, page_size=page_size)
    for item in data.get("items") or []:
        itinerary = item.get("itinerary")
        if itinerary:
            item["itinerary"] = _recompute_costs(itinerary)
    return data


@router.get("/trips/{trip_id}")
async def get_trip(
    trip_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    trip = db.get_trip(trip_id, user["id"])
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    if trip.get("itinerary"):
        trip["itinerary"] = _recompute_costs(trip["itinerary"])
    return trip


@router.get("/trips/{trip_id}/versions")
async def get_trip_versions(
    trip_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    trip = db.get_trip(trip_id, user["id"])
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    return db.list_versions(trip_id)


@router.get("/trips/{trip_id}/live-alerts")
async def trip_live_alerts(
    trip_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    trip = db.get_trip(trip_id, user["id"])
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    itinerary = trip.get("itinerary") or {}
    params = itinerary.get("params") or {}
    city = itinerary.get("city") or params.get("city") or ""
    departure_date = params.get("departure_date") or ""
    days = max(1, len(itinerary.get("days", []) or []) or 1)
    alerts: list[dict[str, Any]] = []

    if departure_date and city:
        await _sync_weather(itinerary, city, departure_date, days)
        if itinerary.get("weather"):
            alerts.append(
                {
                    "type": "weather",
                    "level": "info",
                    "title": "未来几天天气",
                    "content": itinerary.get("weather_advice") or "",
                }
            )
            for item in itinerary["weather"]:
                if "雨" in str(item.get("text", "")):
                    alerts.append(
                        {
                            "type": "weather_risk",
                            "level": "warning",
                            "title": f"{item.get('date')} 有降雨",
                            "content": "建议带伞并预留弹性时间，必要时调整当天行程。",
                        }
                    )
            for item in itinerary.get("weather_warnings") or []:
                alerts.append(
                    {
                        "type": "warning_alert",
                        "level": "danger",
                        "title": item.get("title") or "天气预警",
                        "content": (item.get("text") or "")[:200],
                    }
                )
        else:
            alerts.append(
                {
                    "type": "weather_unavailable",
                    "level": "info",
                    "title": "当天天气暂不可查",
                    "content": itinerary.get("weather_notice") or "暂无法获取该日实时天气。",
                }
            )
        db.update_trip(
            trip_id,
            trip["version"],
            trip["params"],
            itinerary,
            status=trip["status"],
            title=trip["title"],
            city=trip["city"],
        )
    else:
        alerts.append(
            {
                "type": "date_required",
                "level": "info",
                "title": "补充出发日期",
                "content": "设置出发日期后，可查看未来几天的实时天气与官方预警。",
            }
        )

    hot_spots = ("故宫", "长城", "迪士尼", "大熊猫", "环球影城", "颐和园", "天安门")
    for day in itinerary.get("days", []) or []:
        for item in day.get("attractions", []) or []:
            name = item.get("name", "")
            if any(k in name for k in hot_spots):
                alerts.append(
                    {
                        "type": "booking",
                        "level": "warning",
                        "title": f"{name} 需提前预约",
                        "content": "热门景区建议提前 1-7 天在官方渠道预约购票，避免现场限流。",
                    }
                )
                break

    return {"trip_id": trip_id, "alerts": alerts, "itinerary": itinerary}


@router.post("/trips/{trip_id}/departure-date")
async def update_departure_date(
    trip_id: str,
    req: DepartureDateUpdate,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    trip = db.get_trip(trip_id, user["id"])
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    params = dict(trip.get("params") or {})
    params["departure_date"] = req.departure_date
    itinerary = trip.get("itinerary") or {}
    itinerary_params = itinerary.setdefault("params", {})
    itinerary_params["departure_date"] = req.departure_date
    city = itinerary.get("city") or params.get("city") or ""
    days = max(1, len(itinerary.get("days", []) or []) or 1)
    await _sync_weather(itinerary, city, req.departure_date, days)
    db.update_trip(
        trip_id,
        trip["version"],
        params,
        itinerary,
        status=trip["status"],
        title=trip["title"],
        city=trip["city"],
    )
    return {
        "trip_id": trip_id,
        "itinerary": itinerary,
        "departure_date": req.departure_date,
    }


@router.post("/trips/{trip_id}/publish")
async def publish_trip(
    trip_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_verified),
):
    trip = db.get_trip(trip_id, user["id"])
    if not trip:
        raise HTTPException(status_code=404, detail="行程不存在")
    db.update_trip(
        trip_id,
        trip["version"],
        trip["params"],
        trip["itinerary"],
        "published",
    )
    audit(db, user["id"], "publish_trip", "trip", trip_id)
    return {"status": "ok"}


@router.delete("/trips/{trip_id}")
async def delete_trip(
    trip_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    deleted = db.delete_trip(trip_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="行程不存在或不归属当前用户")
    audit(db, user["id"], "delete_trip", "trip", trip_id)
    return {"status": "ok"}


@router.get("/guides")
async def list_guides(
    status: str | None = None,
    page: int = 1,
    page_size: int = 6,
    city: str = "",
    keyword: str = "",
    sort: str = "hot",
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    data = db.paginate_guides(
        status,
        user_id=user["id"],
        page=page,
        page_size=page_size,
        city=city,
        keyword=keyword,
        sort=sort,
    )
    for item in data.get("items", []) or []:
        author = db.query_one(
            "SELECT username, nickname, avatar FROM users WHERE id = ?",
            (item.get("user_id"),),
        )
        if author:
            item["author_nickname"] = author["nickname"] or author["username"]
            item["author_avatar"] = author["avatar"] or ""
        item["is_following"] = db.is_following(
            user["id"], int(item.get("user_id") or 0)
        )
    return data


@router.post("/guides")
async def create_guide(
    req: GuideCreate,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    city = req.city
    if req.trip_id:
        trip = db.get_trip(req.trip_id, user["id"])
        if not trip:
            raise HTTPException(status_code=404, detail="行程不存在")
        city = trip.get("city") or city
    guide_id = db.create_guide(
        user["id"],
        req.title,
        city,
        req.content,
        req.source,
        trip_id=req.trip_id,
        images=req.images,
    )
    guide = db.get_guide(guide_id)
    db.create_review_if_missing(
        "guide",
        guide_id,
        "pending",
        req.title,
        guide,
    )
    metrics.record_review("created")
    audit(db, user["id"], "create_guide", "guide", guide_id)
    return {"id": guide_id, "status": "pending"}


@router.post("/guides/upload")
async def create_guide_upload(
    title: str = Form(...),
    content: str = Form(...),
    trip_id: str = Form(""),
    city: str = Form(""),
    images: list[UploadFile] = File(default=[]),
    db: Database = Depends(get_db),
    user: dict = Depends(require_verified),
):
    if trip_id:
        trip = db.get_trip(trip_id, user["id"])
        if not trip:
            raise HTTPException(status_code=404, detail="行程不存在")
        city = trip.get("city") or city
    guide_id = db.create_guide(
        user["id"], title, city, content, trip_id=trip_id
    )
    saved: list[str] = []
    settings = get_settings()
    upload_root = Path(settings.db_dir) / "uploads" / "guides" / guide_id
    upload_root.mkdir(parents=True, exist_ok=True)
    for image in images:
        if image.content_type and not image.content_type.startswith("image/"):
            continue
        suffix = Path(image.filename or "").suffix.lower()[:10] or ".jpg"
        filename = f"{uuid.uuid4().hex[:10]}{suffix}"
        data = await image.read()
        (upload_root / filename).write_bytes(data)
        saved.append(f"/uploads/guides/{guide_id}/{filename}")
    if saved:
        db.update_guide_images(guide_id, saved)
    guide = db.get_guide(guide_id)
    db.create_review_if_missing(
        "guide",
        guide_id,
        "pending",
        title,
        guide,
    )
    metrics.record_review("created")
    audit(db, user["id"], "create_guide", "guide", guide_id)
    return {"id": guide_id, "status": "pending", "images": saved}


@router.get("/guides/mine")
async def my_guides(
    page: int = 1,
    page_size: int = 6,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    return db.paginate_my_guides(user["id"], page=page, page_size=page_size)


@router.get("/guides/liked")
async def liked_guides(
    page: int = 1,
    page_size: int = 6,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    return db.paginate_liked_guides(user["id"], page=page, page_size=page_size)


@router.delete("/guides/{guide_id}")
async def delete_guide(
    guide_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    guide = db.get_guide(guide_id)
    if not guide or guide.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="攻略不存在")
    deleted = db.delete_guide(guide_id, user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="攻略不存在")
    settings = get_settings()
    upload_dir = Path(settings.db_dir) / "uploads" / "guides" / guide_id
    shutil.rmtree(upload_dir, ignore_errors=True)
    audit(db, user["id"], "delete_guide", "guide", guide_id)
    return {"status": "ok"}


@router.get("/guides/{guide_id}")
async def get_guide(
    guide_id: str,
    db: Database = Depends(get_db),
    viewer: dict | None = Depends(get_optional_user),
):
    guide = db.get_guide(guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="攻略不存在")
    author = db.query_one(
        "SELECT username, nickname, avatar FROM users WHERE id = ?",
        (guide.get("user_id"),),
    )
    if author:
        guide["username"] = author["username"]
        guide["author_nickname"] = author["nickname"] or author["username"]
        guide["author_avatar"] = author["avatar"] or ""
    author_profile = db.get_user_profile(int(guide.get("user_id") or 0))
    if author_profile:
        guide["followers_count"] = author_profile["followers_count"]
        guide["following_count"] = author_profile["following_count"]
    guide["is_following"] = bool(
        viewer
        and db.is_following(viewer["id"], int(guide.get("user_id") or 0))
    )
    if guide.get("trip_id"):
        trip = db.get_trip(guide["trip_id"])
        if trip:
            guide["trip_itinerary"] = trip.get("itinerary") or {}
    guide["comments"] = db.list_comments(guide_id)
    return guide


@router.post("/guides/{guide_id}/copy-trip")
async def copy_guide_trip(
    guide_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    guide = db.get_guide(guide_id)
    if not guide:
        raise HTTPException(status_code=404, detail="攻略不存在")
    if not guide.get("trip_id"):
        raise HTTPException(status_code=400, detail="该攻略没有关联行程")
    trip = db.get_trip(guide["trip_id"])
    if not trip:
        raise HTTPException(status_code=400, detail="攻略关联的行程已不存在")
    params = dict(trip.get("params") or {})
    params["source_text"] = f"来自攻略：{guide.get('title', '')}"
    itinerary = trip.get("itinerary") or {}
    itinerary["params"] = params
    days = len(itinerary.get("days", []) or []) or params.get("days", 1)
    travelers = params.get("travelers", 1) or 1
    trip_id = db.create_trip(
        user["id"],
        f"{guide.get('city', '')} · {days}天{travelers}人（攻略）",
        guide.get("city", "") or trip.get("city", ""),
        params,
        itinerary,
    )
    audit(db, user["id"], "copy_guide_trip", "guide", guide_id)
    return {"trip_id": trip_id, "status": "ok"}


@router.post("/guides/{guide_id}/like")
async def like_guide(
    guide_id: str,
    body: dict[str, bool],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    if not db.get_guide(guide_id):
        raise HTTPException(status_code=404, detail="攻略不存在")
    liked = body.get("liked", True)
    db.like_guide(guide_id, user["id"], liked)
    guide = db.get_guide(guide_id)
    return {"liked": liked, "likes": guide["likes"], "favorites": guide["favorites"]}


@router.post("/guides/{guide_id}/favorite")
async def favorite_guide(
    guide_id: str,
    body: dict[str, bool],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    if not db.get_guide(guide_id):
        raise HTTPException(status_code=404, detail="攻略不存在")
    favorited = body.get("favorited", True)
    db.favorite_guide(guide_id, user["id"], favorited)
    guide = db.get_guide(guide_id)
    return {
        "favorited": favorited,
        "likes": guide["likes"],
        "favorites": guide["favorites"],
    }


@router.post("/guides/{guide_id}/comments")
async def comment_guide(
    guide_id: str,
    req: CommentCreate,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    comment_id = db.add_comment(guide_id, user["id"], req.content)
    return {"id": comment_id}


@router.get("/favorites")
async def list_favorites(
    page: int = 1,
    page_size: int = 6,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    return db.paginate_favorites(user["id"], page=page, page_size=page_size)


@router.get("/admin/guides")
async def admin_guides(
    page: int = 1,
    page_size: int = 10,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    data = db.paginate_guides(
        None,
        user_id=user["id"],
        page=page,
        page_size=page_size,
        sort="new",
    )
    for item in data.get("items") or []:
        author = db.query_one(
            "SELECT username, nickname, avatar FROM users WHERE id = ?",
            (item.get("user_id"),),
        )
        if author:
            item["author_nickname"] = author["nickname"] or author["username"]
            item["author_avatar"] = author["avatar"] or ""
    return data


@router.get("/admin/reviews")
async def admin_reviews(
    status: str | None = None,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    reviews = db.list_reviews(status, target_type="guide")
    seen: set[str] = set()
    unique = []
    for item in reviews:
        target_id = str(item.get("target_id") or "")
        if target_id in seen:
            continue
        seen.add(target_id)
        unique.append(item)
    return unique


@router.get("/admin/prices")
async def admin_prices(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_place_prices()


@router.post("/admin/prices")
async def admin_upsert_price(
    body: dict[str, Any],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    price_id = db.upsert_place_price(
        str(body.get("place_name", "")).strip(),
        str(body.get("city", "")).strip(),
        float(body.get("price") or 0),
        source=str(body.get("source") or "人工维护"),
        source_url=str(body.get("source_url") or ""),
        note=str(body.get("note") or ""),
        status=str(body.get("status") or "approved"),
    )
    audit(db, user["id"], "upsert_price", "place_price", price_id)
    return {"id": price_id}


@router.delete("/admin/prices/{price_id}")
async def admin_delete_price(
    price_id: str,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    db.delete_place_price(price_id)
    audit(db, user["id"], "delete_price", "place_price", price_id)
    return {"status": "ok"}


@router.post("/prices/feedback")
async def submit_price_feedback(
    body: dict[str, Any],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("user")),
):
    place_name = str(body.get("place_name", "")).strip()
    if not place_name or float(body.get("price") or 0) <= 0:
        raise HTTPException(status_code=400, detail="地点和价格不能为空")
    feedback_id = db.submit_price_feedback(
        place_name,
        str(body.get("city", "")).strip(),
        float(body.get("price") or 0),
        user["id"],
    )
    return {"id": feedback_id, "status": "pending"}


@router.get("/admin/price-feedback")
async def admin_price_feedback(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_price_feedback()


@router.post("/admin/price-feedback/{feedback_id}/decide")
async def decide_price_feedback(
    feedback_id: str,
    body: dict[str, Any],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    status = str(body.get("status") or "approved")
    if status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="无效状态")
    db.decide_price_feedback(feedback_id, status, user["id"])
    audit(db, user["id"], "decide_price_feedback", "price_feedback", feedback_id, status)
    return {"status": "ok"}


@router.post("/admin/reviews/{review_id}/decide")
async def decide_review(
    review_id: str,
    req: ReviewDecision,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    updated = db.decide_review(review_id, req.status, req.note, user["id"])
    if not updated:
        raise HTTPException(status_code=404, detail="审核任务不存在或已处理")
    review = db.query_one("SELECT * FROM reviews WHERE id = ?", (review_id,))
    if review and review["target_type"] == "guide":
        db.update_guide_status(review["target_id"], req.status, req.note)
    elif review and review["target_type"] == "trip":
        trip = db.get_trip(review["target_id"])
        if trip:
            db.update_trip(
                trip["id"],
                trip["version"],
                trip["params"],
                trip["itinerary"],
                "approved" if req.status == "approved" else "draft",
            )
    metrics.record_review(req.status)
    audit(db, user["id"], f"review_{req.status}", "review", review_id)
    return {"status": "ok"}


@router.get("/admin/users")
async def admin_users(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_users()


@router.post("/admin/users/{user_id}/status")
async def admin_set_user_status(
    user_id: int,
    body: dict[str, str],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("super_admin")),
):
    if body.get("status") not in ("active", "muted", "banned"):
        raise HTTPException(status_code=400, detail="无效状态")
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    db.set_user_status(user_id, body["status"])
    audit(
        db, user["id"], "set_user_status", "user", str(user_id), body["status"]
    )
    return {"status": "ok"}


@router.post("/admin/users/{user_id}/role")
async def admin_set_user_role(
    user_id: int,
    body: dict[str, str],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("super_admin")),
):
    role = body.get("role", "")
    if role not in ("user", "admin", "super_admin"):
        raise HTTPException(status_code=400, detail="无效角色")
    target = db.get_user_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target["id"] == user["id"]:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    db.set_user_role(user_id, role)
    audit(db, user["id"], "set_user_role", "user", str(user_id), role)
    return {"status": "ok"}


@router.get("/admin/audit-logs")
async def admin_audit_logs(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_audit_logs(200)


@router.get("/admin/login-audit")
async def admin_login_audit(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_login_audit(200)


@router.get("/admin/recommend-slots")
async def admin_recommend_slots(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return db.list_recommend_slots()


@router.post("/admin/recommend-slots")
async def admin_set_recommend_slot(
    body: dict[str, Any],
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    db.set_recommend_slot(
        str(body.get("slot", "")),
        str(body.get("guide_id", "")),
        bool(body.get("enabled", True)),
    )
    return {"status": "ok"}


@router.get("/metrics")
async def get_metrics(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    snapshot = metrics.snapshot()
    runs = db.agent_run_summary()
    snapshot["request_count"] = runs["total_runs"]
    snapshot["success_count"] = runs["success_runs"]
    snapshot["failure_count"] = runs["failed_runs"]
    snapshot["success_rate"] = runs["success_rate"]
    snapshot["avg_latency_ms"] = runs["avg_latency_ms"]
    snapshot["p95_latency_ms"] = runs["p95_latency_ms"]
    snapshot["prompt_tokens"] = runs["prompt_tokens"]
    snapshot["completion_tokens"] = runs["completion_tokens"]
    snapshot["total_tokens"] = runs["total_tokens"]
    return snapshot


@router.post("/metrics/reset")
async def reset_metrics(user: dict = Depends(require_role("admin", "super_admin"))):
    metrics.reset()
    return {"status": "ok"}


@router.get("/admin/runs")
async def admin_runs(
    page: int = 1,
    page_size: int = 20,
    user_id: int | None = None,
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    page = max(1, page)
    limit = max(1, min(50, page_size))
    offset = (page - 1) * limit
    return {
        "items": db.list_agent_runs(user_id=user_id, limit=limit, offset=offset),
        "page": page,
        "page_size": limit,
    }


@router.get("/admin/stats")
async def admin_stats(
    db: Database = Depends(get_db),
    user: dict = Depends(require_role("admin", "super_admin")),
):
    return {
        "runs": db.agent_run_summary(),
        "metrics": metrics.snapshot(),
    }


@router.get("/eval/run")
async def run_eval(user: dict = Depends(require_role("admin", "super_admin"))):
    return await run_demo_eval()


@router.get("/health")
async def health():
    return {"status": "ok", "app": "ai-travel-agent"}

