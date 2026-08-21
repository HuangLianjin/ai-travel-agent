"""全功能流程冒烟测试：认证/规划/调整/社区/收藏/审核/RBAC/指标/评测。"""

from __future__ import annotations

import json
import time

import httpx

BASE = "http://127.0.0.1:8000/api"
client = httpx.Client(timeout=120)
results: list[tuple[str, bool, str]] = []


def check(name: str, fn):
    try:
        data = fn()
        if isinstance(data, httpx.Response):
            data = data.json()
        results.append((name, True, json.dumps(data, ensure_ascii=False)[:160]))
        return data
    except Exception as exc:
        body = ""
        if isinstance(exc, httpx.HTTPStatusError):
            body = exc.response.text[:160]
        results.append((name, False, f"{exc} {body}"))
        return None


def check_denied(name: str, fn):
    try:
        resp = fn()
        if isinstance(resp, httpx.Response):
            status = resp.status_code
            ok = status in (401, 403)
            results.append((name, ok, str(status)))
            return
        results.append((name, False, "expected 403, got success"))
    except httpx.HTTPStatusError as exc:
        ok = exc.response.status_code in (401, 403)
        results.append((name, ok, str(exc.response.status_code)))


def auth(username: str, password: str) -> dict:
    resp = client.post(f"{BASE}/auth/login", json={"username": username, "password": password})
    resp.raise_for_status()
    return resp.json()


def h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    check("GET /health", lambda: client.get(f"{BASE}/health").raise_for_status())

    suffix = str(int(time.time()))[-6:]
    new_user = f"smoke_{suffix}"
    check(
        "POST /auth/register",
        lambda: client.post(
            f"{BASE}/auth/register",
            json={"username": new_user, "password": "smoke123"},
        ).raise_for_status(),
    )

    demo = check("POST /auth/login demo", lambda: auth("demo", "demo123"))
    admin = check("POST /auth/login admin", lambda: auth("admin", "admin123"))
    smoke = check(f"POST /auth/login {new_user}", lambda: auth(new_user, "smoke123"))
    if not (demo and admin and smoke):
        _finish()
        return

    dh, ah, sh = h(demo["access_token"]), h(admin["access_token"]), h(smoke["access_token"])

    chat1 = check(
        "POST /api/chat create",
        lambda: client.post(
            f"{BASE}/chat",
            headers=dh,
            json={"message": "北京三天，预算3000，喜欢历史和美食"},
        ).raise_for_status(),
    )
    trip_id = chat1.get("trip_id") if chat1 else None

    chat2 = check(
        "POST /api/chat adjust",
        lambda: client.post(
            f"{BASE}/chat",
            headers=dh,
            json={"message": "当天轻松一些，增加铜锅涮肉", "trip_id": trip_id},
        ).raise_for_status(),
    )

    reg = check(
        "POST /api/chat days/budget adjust",
        lambda: client.post(
            f"{BASE}/chat",
            headers=dh,
            json={"message": "改成6天，预算不能超过2000", "trip_id": trip_id},
        ).raise_for_status(),
    )
    if reg:
        days_ok = len((reg.get("itinerary") or {}).get("days", [])) == 6
        budget = (reg.get("itinerary") or {}).get("budget", {})
        budget_ok = int(budget.get("estimated_total", 0)) <= 2000
        results.append(
            (
                "Days/Budget constraint respected",
                days_ok and budget_ok,
                f"days={len((reg.get('itinerary') or {}).get('days', []))}, budget={budget.get('estimated_total')}",
            )
        )

    check(
        "GET /api/trips",
        lambda: client.get(f"{BASE}/trips", headers=dh).raise_for_status(),
    )
    check(
        "GET /api/trips/{id}",
        lambda: client.get(f"{BASE}/trips/{trip_id}", headers=dh).raise_for_status(),
    )
    check(
        "GET /api/trips/{id}/versions",
        lambda: client.get(f"{BASE}/trips/{trip_id}/versions", headers=dh).raise_for_status(),
    )

    guide = check(
        "POST /api/guides",
        lambda: client.post(
            f"{BASE}/guides",
            headers=dh,
            json={
                "title": "冒烟测试攻略",
                "city": "北京",
                "content": "第一天故宫和南锣鼓巷，第二天颐和园，晚上吃涮肉。",
            },
        ).raise_for_status(),
    )
    guide_id = guide.get("id") if guide else None

    check(
        "GET /api/guides",
        lambda: client.get(f"{BASE}/guides", headers=dh).raise_for_status(),
    )
    check(
        "POST /api/guides/{id}/like",
        lambda: client.post(
            f"{BASE}/guides/{guide_id}/like",
            headers=dh,
            json={"liked": True},
        ).raise_for_status(),
    )
    check(
        "POST /api/guides/{id}/favorite",
        lambda: client.post(
            f"{BASE}/guides/{guide_id}/favorite",
            headers=dh,
            json={"favorited": True},
        ).raise_for_status(),
    )
    check(
        "POST /api/guides/{id}/comments",
        lambda: client.post(
            f"{BASE}/guides/{guide_id}/comments",
            headers=dh,
            json={"content": "这条攻略很实用"},
        ).raise_for_status(),
    )
    check(
        "GET /api/guides/{id}",
        lambda: client.get(f"{BASE}/guides/{guide_id}", headers=dh).raise_for_status(),
    )

    reviews = check(
        "GET /api/admin/reviews",
        lambda: client.get(f"{BASE}/admin/reviews?status=pending", headers=ah).raise_for_status(),
    )
    if reviews:
        guide_review = next(
            (r for r in reviews if r.get("target_id") == guide_id), None
        )
        if guide_review:
            check(
                "POST /api/admin/reviews/{id}/decide approve",
                lambda: client.post(
                    f"{BASE}/admin/reviews/{guide_review['id']}/decide",
                    headers=ah,
                    json={"status": "approved", "note": "内容合规"},
                ).raise_for_status(),
            )

    cross = check(
        "GET /api/guides cross-user visibility",
        lambda: client.get(
            f"{BASE}/guides?status=approved&page=1&page_size=50",
            headers=sh,
        ).raise_for_status(),
    )
    if cross and guide_id and not any(
        item.get("id") == guide_id for item in (cross.get("items") or [])
    ):
        results.append(
            ("Cross-user guide visible", False, "approved guide not visible to another user")
        )

    check(
        "GET /api/favorites",
        lambda: client.get(f"{BASE}/favorites", headers=dh).raise_for_status(),
    )
    if trip_id:
        trip_reviews = [
            r
            for r in (reviews or [])
            if r.get("target_id") == trip_id and r.get("status") == "pending"
        ]
        trip_review = (
            max(trip_reviews, key=lambda r: r.get("created_at") or "")
            if trip_reviews
            else None
        )
        if trip_review:
            check(
                "POST /api/admin/reviews/{id}/decide trip approve",
                lambda: client.post(
                    f"{BASE}/admin/reviews/{trip_review['id']}/decide",
                    headers=ah,
                    json={"status": "approved", "note": "路线合理"},
                ).raise_for_status(),
            )
        check(
            "POST /api/trips/{id}/publish",
            lambda: client.post(f"{BASE}/trips/{trip_id}/publish", headers=dh).raise_for_status(),
        )

    check(
        "DELETE /api/trips/{id}",
        lambda: client.delete(f"{BASE}/trips/{trip_id}", headers=dh).raise_for_status(),
    )
    check(
        "GET /api/admin/users",
        lambda: client.get(f"{BASE}/admin/users", headers=ah).raise_for_status(),
    )
    smoke_user_id = smoke["user"]["id"]
    check(
        "POST /api/admin/users/{id}/status mute",
        lambda: client.post(
            f"{BASE}/admin/users/{smoke_user_id}/status",
            headers=ah,
            json={"status": "muted"},
        ).raise_for_status(),
    )
    check(
        "POST /api/admin/users/{id}/status active",
        lambda: client.post(
            f"{BASE}/admin/users/{smoke_user_id}/status",
            headers=ah,
            json={"status": "active"},
        ).raise_for_status(),
    )
    check(
        "GET /api/admin/audit-logs",
        lambda: client.get(f"{BASE}/admin/audit-logs", headers=ah).raise_for_status(),
    )
    check(
        "POST /api/admin/recommend-slots",
        lambda: client.post(
            f"{BASE}/admin/recommend-slots",
            headers=ah,
            json={"slot": "home_1", "guide_id": guide_id, "enabled": True},
        ).raise_for_status(),
    )
    check(
        "GET /api/admin/recommend-slots",
        lambda: client.get(f"{BASE}/admin/recommend-slots", headers=ah).raise_for_status(),
    )

    check(
        "GET /api/metrics admin",
        lambda: client.get(f"{BASE}/metrics", headers=ah).raise_for_status(),
    )
    check(
        "POST /api/metrics/reset admin",
        lambda: client.post(f"{BASE}/metrics/reset", headers=ah).raise_for_status(),
    )
    check(
        "GET /api/eval/run",
        lambda: client.get(f"{BASE}/eval/run", headers=ah).raise_for_status(),
    )

    check_denied(
        "RBAC demo cannot GET /admin/users",
        lambda: client.get(f"{BASE}/admin/users", headers=dh),
    )
    check_denied(
        "RBAC demo cannot GET /metrics",
        lambda: client.get(f"{BASE}/metrics", headers=dh),
    )
    check_denied(
        "RBAC demo cannot reset metrics",
        lambda: client.post(f"{BASE}/metrics/reset", headers=dh),
    )

    _finish()


def _finish() -> None:
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== 全功能冒烟结果: {passed}/{len(results)} 通过 ===\n")
    for name, ok, detail in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            print(f"      {detail}")


if __name__ == "__main__":
    main()

