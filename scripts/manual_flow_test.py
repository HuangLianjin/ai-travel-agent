"""本地全流程冒烟 + 对抗性测试脚本。

用法（需先启动测试服务）：
  python scripts/manual_flow_test.py http://127.0.0.1:8010 data/flow-test.db
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.security import generate_totp_secret, hash_password, totp_code  # noqa: E402


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
    db_path = Path(sys.argv[2] if len(sys.argv) > 2 else "data/flow-test.db")
    client = httpx.Client(base_url=base, timeout=120)
    skip_chat = "--skip-chat" in sys.argv
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        print(("PASS" if ok else "FAIL"), name, detail)

    def db_code(phone: str, purpose: str) -> str | None:
        con = sqlite3.connect(db_path)
        try:
            row = con.execute(
                "SELECT code FROM verification_codes "
                "WHERE phone = ? AND purpose = ? AND used = 0 "
                "ORDER BY id DESC LIMIT 1",
                (phone, purpose),
            ).fetchone()
            return row[0] if row else None
        finally:
            con.close()

    def insert_user(username: str, password: str, phone: str, verified: int) -> None:
        con = sqlite3.connect(db_path)
        try:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            con.execute(
                "INSERT INTO users (username, password_hash, role, status, created_at, "
                "phone, phone_verified) VALUES (?, ?, 'user', 'active', ?, ?, ?)",
                (username, hash_password(password), now, phone, verified),
            )
            con.commit()
        finally:
            con.close()

    # 1. 健康检查
    r = client.get("/api/health")
    check("health", r.status_code == 200)

    # 2. 注册：非法手机号 / 弱密码 / 错误验证码 / 正确验证码
    r = client.post("/api/auth/send-code", json={"phone": "123", "purpose": "register"})
    check("send-code bad phone rejected", r.status_code == 400)

    phone = "13812345678"
    r = client.post("/api/auth/send-code", json={"phone": phone, "purpose": "register"})
    check("send-code register", r.status_code == 200)
    code = db_code(phone, "register")
    check("register code stored", bool(code))

    r = client.post(
        "/api/auth/register",
        json={"username": "badpass", "password": "12345678", "phone": phone, "code": code},
    )
    check("weak password rejected", r.status_code == 400)

    r = client.post(
        "/api/auth/register",
        json={"username": "flowuser", "password": "FlowPass#2026", "phone": phone, "code": "000000"},
    )
    check("wrong register code rejected", r.status_code == 400)

    r = client.post(
        "/api/auth/register",
        json={"username": "flowuser", "password": "FlowPass#2026", "phone": phone, "code": code},
    )
    check("register with correct code", r.status_code == 200)

    r = client.post(
        "/api/auth/register",
        json={"username": "flowuser2", "password": "FlowPass#2026", "phone": phone, "code": "000000"},
    )
    check("duplicate phone rejected", r.status_code == 409)

    # 3. 正常登录 + refresh 轮换
    r = client.post(
        "/api/auth/login",
        json={"username": "flowuser", "password": "FlowPass#2026"},
    )
    check("login new user", r.status_code == 200 and r.json().get("phone_verified") is True)
    login = r.json()
    access = login["access_token"]
    refresh = login["refresh_token"]
    headers = {"Authorization": f"Bearer {access}"}

    r = client.post(
        "/api/auth/refresh", json={"refresh_token": refresh}
    )
    check("refresh rotates token", r.status_code == 200)
    new_refresh = r.json()["refresh_token"]
    r = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    check("old refresh rejected after rotation", r.status_code == 401)
    refresh = new_refresh

    # 4. 未验证用户不能生成行程/发布攻略
    insert_user("unverified_user", "Unverified#2026", "13800000001", 0)
    r = client.post(
        "/api/auth/login",
        json={"username": "unverified_user", "password": "Unverified#2026"},
    )
    uv = r.json()
    uv_headers = {"Authorization": f"Bearer {uv['access_token']}"}
    r = client.post(
        "/api/chat",
        headers=uv_headers,
        json={"message": "北京3天2人"},
    )
    check("unverified chat blocked", r.status_code == 403)

    # 5. 管理员强制改密 + 权限
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminInit#2026"})
    check("admin login flags forced change", r.status_code == 200 and r.json().get("must_change_password") is True)
    admin = r.json()
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}
    r = client.post(
        "/api/chat",
        headers=admin_headers,
        json={"message": "北京3天2人"},
    )
    check("admin chat blocked before password change", r.status_code == 403)

    r = client.post(
        "/api/auth/change-password",
        headers=admin_headers,
        json={"old_password": "AdminInit#2026", "new_password": "Strong#2026x"},
    )
    check("admin change password", r.status_code == 200)
    r = client.post(
        "/api/auth/refresh",
        json={"refresh_token": admin["refresh_token"]},
    )
    check("old admin refresh revoked after change", r.status_code == 401)

    r = client.post("/api/auth/login", json={"username": "admin", "password": "Strong#2026x"})
    check("admin login after change", r.status_code == 200 and r.json().get("must_change_password") is False)
    admin = r.json()
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    # 6. 2FA 开启、登录校验、关闭
    r = client.get("/api/auth/2fa/setup", headers=headers)
    check("2fa setup", r.status_code == 200)
    secret = r.json()["secret"]
    r = client.post(
        "/api/auth/2fa/enable",
        headers=headers,
        json={"secret": secret, "code": "000000"},
    )
    check("2fa enable wrong code", r.status_code == 400)
    r = client.post(
        "/api/auth/2fa/enable",
        headers=headers,
        json={"secret": secret, "code": totp_code(secret)},
    )
    check("2fa enable", r.status_code == 200)
    client.post("/api/auth/logout", json={"refresh_token": refresh})
    r = client.post(
        "/api/auth/login",
        json={"username": "flowuser", "password": "FlowPass#2026", "totp_code": "000000"},
    )
    check("2fa login wrong code", r.status_code == 401)
    r = client.post(
        "/api/auth/login",
        json={"username": "flowuser", "password": "FlowPass#2026", "totp_code": totp_code(secret)},
    )
    check("2fa login correct code", r.status_code == 200)
    login2 = r.json()
    headers = {"Authorization": f"Bearer {login2['access_token']}"}
    r = client.post(
        "/api/auth/2fa/disable",
        headers=headers,
        json={"code": totp_code(secret)},
    )
    check("2fa disable", r.status_code == 200)

    # 7. 登录失败锁定
    for i in range(5):
        client.post("/api/auth/login", json={"username": "flowuser", "password": "wrong-pass"})
    r = client.post(
        "/api/auth/login",
        json={"username": "flowuser", "password": "FlowPass#2026"},
    )
    check("account locked after failures", r.status_code == 423)
    r = client.get("/api/profile/me", headers=headers)
    check("locked account old token blocked", r.status_code == 403)

    # 8. 发码限流
    r = client.post("/api/auth/send-code", json={"phone": "13812345679", "purpose": "register"})
    first = r.status_code
    r = client.post("/api/auth/send-code", json={"phone": "13812345679", "purpose": "register"})
    check("send-code rate limited", first == 200 and r.status_code == 429)

    # 9. 行程生成（默认执行；--skip-chat 可跳过，避免消耗搜索配额）
    if skip_chat:
        check("chat skipped", True)
        trip_id = ""
    else:
        time.sleep(1)
        r = client.post(
            "/api/chat",
            headers=headers,
            json={"message": "北京3天2人，预算3000"},
        )
        check("chat generates plan", r.status_code == 200, r.text[:200])
        plan = r.json() if r.status_code == 200 else {}
        trip_id = plan.get("trip_id") or ""
        check("chat returns trip id", bool(trip_id))

    # 10. 攻略发布 + 审核 + 广场可见（用新的已验证用户，避免受锁定影响）
    insert_user("guide_user", "GuidePass#2026", "13800000002", 1)
    r = client.post("/api/auth/login", json={"username": "guide_user", "password": "GuidePass#2026"})
    guide_login = r.json()
    guide_headers = {"Authorization": f"Bearer {guide_login['access_token']}"}
    fd = {"title": "测试攻略", "content": "这是一条全流程测试攻略内容。", "city": "北京"}
    r = client.post("/api/guides/upload", headers=guide_headers, data=fd)
    check("guide upload pending", r.status_code == 200 and r.json().get("status") == "pending")
    guide_id = r.json().get("id", "")
    r = client.get("/api/admin/reviews", headers=admin_headers)
    check("admin reviews list", r.status_code == 200)
    review = next((x for x in r.json() if x.get("target_id") == guide_id), None)
    check("guide review found", bool(review))
    if review:
        r = client.post(
            f"/api/admin/reviews/{review['id']}/decide",
            headers=admin_headers,
            json={"status": "approved", "note": "通过"},
        )
        check("admin approve guide", r.status_code == 200)
    r = client.get("/api/guides?status=approved", headers=guide_headers)
    check("approved guide in plaza", r.status_code == 200 and any(g.get("id") == guide_id for g in r.json().get("items", [])))

    # 11. 权限：普通用户不能进管理接口
    r = client.get("/api/admin/users", headers=guide_headers)
    check("normal user denied admin", r.status_code == 403)
    r = client.get("/api/admin/users", headers=admin_headers)
    check("super admin can list users", r.status_code == 200)

    failed = [x for x in results if not x[1]]
    print(f"\nRESULT: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
