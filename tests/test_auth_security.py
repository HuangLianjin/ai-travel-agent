import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import get_db
from app.db import Database
from app.main import app
from app.security import (
    create_access_token,
    create_refresh_token,
    generate_totp_secret,
    hash_token,
    totp_code,
    validate_password_policy,
    verify_totp,
)

TEST_TABLES = [
    "users",
    "trips",
    "itinerary_versions",
    "conversations",
    "guides",
    "comments",
    "likes",
    "favorites",
    "follows",
    "reviews",
    "audit_logs",
    "refresh_tokens",
    "login_audit",
    "verification_codes",
    "recommend_slots",
    "agent_runs",
    "eval_failures",
    "user_feedback",
    "place_prices",
    "price_feedback",
]


@pytest.fixture
def db():
    dsn = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://travel:travel@127.0.0.1:5432/travel_test",
    )
    database = Database(dsn)
    database.init_db()
    database.execute(
        "TRUNCATE " + ", ".join(TEST_TABLES) + " RESTART IDENTITY CASCADE"
    )
    yield database
    database.close()


def test_password_policy_rejects_weak_passwords():
    with pytest.raises(ValueError):
        validate_password_policy("alice", "12345678")
    with pytest.raises(ValueError):
        validate_password_policy("alice", "password1")
    with pytest.raises(ValueError):
        validate_password_policy("alice", "alice2026")
    validate_password_policy("alice", "Travel2026")


def test_totp_roundtrip():
    secret = generate_totp_secret()
    assert verify_totp(secret, totp_code(secret))
    assert not verify_totp(secret, "000000")


def test_refresh_token_hash_and_revoke(db):
    uid = db.create_user(
        "security_user",
        "Travel2026",
        email="security@example.com",
        email_verified=1,
    )
    token, token_hash = create_refresh_token()
    assert hash_token(token) == token_hash
    db.create_refresh_token(uid, token_hash, "2099-01-01T00:00:00+00:00")
    assert db.get_refresh_token(token_hash) is not None
    db.revoke_refresh_token(token_hash)
    assert db.get_refresh_token(token_hash) is None


def test_lock_revokes_refresh_tokens(db):
    uid = db.create_user(
        "lock_user",
        "LockPass#2026",
        phone="13800000003",
        phone_verified=1,
    )
    token, token_hash = create_refresh_token()
    db.create_refresh_token(uid, token_hash, "2099-01-01T00:00:00+00:00")
    for _ in range(5):
        db.record_login_failure("lock_user")
    user = db.get_user_by_username("lock_user")
    assert user["locked_until"]
    assert db.get_refresh_token(token_hash) is None


def test_phone_verification_code_flow(db):
    db.save_verification_code(
        "13800000000", "register", "123456", "2099-01-01T00:00:00+00:00"
    )
    row = db.get_verification_code("13800000000", "register")
    assert row and row["code"] == "123456"
    db.mark_code_used(row["id"])
    assert db.get_verification_code("13800000000", "register") is None


def test_new_database_has_no_default_admin(db):
    assert db.get_user_by_username("admin") is None
    assert db.get_user_by_username("demo") is None
    cols = {
        row["column_name"]
        for row in db.query_all(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'users'"
        )
    }
    assert {
        "email",
        "email_verified",
        "phone",
        "phone_verified",
        "totp_secret",
        "must_change_password",
    } <= cols
    tables = {
        row["table_name"]
        for row in db.query_all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    }
    assert "refresh_tokens" in tables
    assert "login_audit" in tables


def test_agent_run_summary_includes_cost_and_intent(db):
    uid = db.create_user(
        "metrics_user",
        "Travel2026",
        email="metrics@example.com",
        email_verified=1,
    )
    db.start_agent_run("run_1", uid, "session_1", "去北京")
    db.save_agent_run(
        "run_1",
        uid,
        "session_1",
        "create",
        "success",
        "去北京",
        {},
        "ok",
        [],
        [],
        prompt_tokens=1000,
        completion_tokens=2000,
        latency_ms=120,
    )
    db.start_agent_run("run_2", uid, "session_2", "调整行程")
    db.save_agent_run(
        "run_2",
        uid,
        "session_2",
        "adjust",
        "failed",
        "调整行程",
        {},
        "",
        [],
        [],
        prompt_tokens=500,
        completion_tokens=500,
        latency_ms=280,
        error="boom",
    )

    summary = db.agent_run_summary(
        days=7,
        input_price_per_1m=2.0,
        output_price_per_1m=8.0,
    )

    assert summary["total_runs"] == 2
    assert summary["success_runs"] == 1
    assert summary["failed_runs"] == 1
    assert summary["success_rate"] == 0.5
    assert summary["total_tokens"] == 4000
    assert summary["estimated_cost_yuan"] == 0.023
    assert {
        row["intent"]: row["n"] for row in summary["by_intent"]
    } == {"create": 1, "adjust": 1}


def test_eval_failure_reflow_lifecycle(db):
    reviewer_id = db.create_user(
        "reviewer",
        "Travel2026",
        role="admin",
        email="reviewer@example.com",
        email_verified=1,
    )
    saved = db.save_eval_failures(
        "eval_20260915",
        [
            {
                "case_id": "t001",
                "title": "北京三天经典游",
                "input_text": "我想去北京玩三天",
                "failure_types": ["keyword_missing"],
                "quality_failures": ["route"],
                "quality_score": 0.75,
                "intent": "create",
                "city": "北京",
                "latency_ms": 320,
            }
        ],
    )

    assert saved == 1
    items = db.list_eval_failures(status="open")
    assert len(items) == 1
    assert items[0]["failure_types"] == ["keyword_missing"]
    assert items[0]["quality_failures"] == ["route"]

    updated = db.update_eval_failure_status(
        items[0]["id"],
        "fixed",
        "已补检索规则",
        reviewer_id,
    )
    assert updated["status"] == "fixed"
    assert updated["fix_note"] == "已补检索规则"
    assert updated["fixed_by"] == reviewer_id
    assert updated["fixed_at"]
    assert db.list_eval_failures(status="open") == []

    summary = db.eval_failure_summary()
    assert summary["total"] == 1
    assert summary["open"] == 0
    assert summary["fixed"] == 1
    assert summary["by_failure_type"]["keyword_missing"] == 1


def test_user_feedback_low_rating_enters_optimization_pool(db):
    user_id = db.create_user(
        "feedback_user",
        "Travel2026",
        email="feedback@example.com",
        email_verified=1,
    )

    feedback_id, low_score = db.save_user_feedback(
        user_id=user_id,
        target_type="trip",
        target_id="trip_1",
        rating=2,
        tags=["路线太赶"],
        comment="第二天的交通安排不合理",
    )

    assert feedback_id > 0
    assert low_score is True
    feedback = db.list_user_feedback(user_id=user_id, limit=10)
    assert feedback[0]["rating"] == 2
    assert feedback[0]["tags"] == ["路线太赶"]
    failures = db.list_eval_failures(status="open")
    assert len(failures) == 1
    assert failures[0]["case_id"] == "trip_1"
    assert failures[0]["failure_types"] == ["user_low_rating"]
    summary = db.user_feedback_summary(days=30)
    assert summary["total"] == 1
    assert summary["avg_rating"] == 2.0
    assert summary["low_ratings"] == 1


def test_admin_observability_endpoints_enforce_permissions(db):
    admin_id = db.create_user(
        "metrics_admin",
        "Travel2026",
        role="admin",
        email="metrics-admin@example.com",
        email_verified=1,
    )
    db.create_user(
        "metrics_reader",
        "Travel2026",
        email="metrics-reader@example.com",
        email_verified=1,
    )
    reader = db.get_user_by_username("metrics_reader")
    feedback_trip_id = db.create_trip(
        reader["id"],
        "反馈测试行程",
        "成都",
        {"city": "成都", "days": 2},
        {"city": "成都", "days": []},
    )
    db.save_eval_failures(
        "eval_api",
        [
            {
                "case_id": "api_case",
                "title": "接口回流样本",
                "failure_types": ["intent_mismatch"],
                "quality_score": 0.5,
                "intent": "ask",
                "city": "成都",
            }
        ],
    )
    settings = get_settings()
    admin_headers = {
        "Authorization": f"Bearer {create_access_token('metrics_admin', 'admin', settings)}"
    }
    reader_headers = {
        "Authorization": f"Bearer {create_access_token('metrics_reader', 'user', settings)}"
    }

    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    try:
        metrics_response = client.get("/api/metrics?days=7", headers=admin_headers)
        assert metrics_response.status_code == 200
        assert "estimated_cost_yuan" in metrics_response.json()
        assert "by_intent" in metrics_response.json()

        feedback_response = client.post(
            "/api/feedback",
            headers=reader_headers,
            json={
                "target_type": "trip",
                "target_id": feedback_trip_id,
                "rating": 2,
                "tags": ["行程太赶"],
                "comment": "希望减少景点",
            },
        )
        assert feedback_response.status_code == 200
        assert feedback_response.json()["added_to_optimization"] is True

        admin_feedback = client.get("/api/admin/feedback", headers=admin_headers)
        assert admin_feedback.status_code == 200
        assert admin_feedback.json()[0]["rating"] == 2

        failures_response = client.get(
            "/api/admin/eval-failures?status=open",
            headers=admin_headers,
        )
        assert failures_response.status_code == 200
        failures = failures_response.json()["items"]
        api_failure = next(item for item in failures if item["case_id"] == "api_case")

        fixed_response = client.post(
            f"/api/admin/eval-failures/{api_failure['id']}/status",
            headers=admin_headers,
            json={"status": "fixed", "note": "已修复"},
        )
        assert fixed_response.status_code == 200
        assert fixed_response.json()["status"] == "fixed"
        assert fixed_response.json()["fixed_by"] == admin_id

        forbidden = client.get("/api/metrics?days=7", headers=reader_headers)
        assert forbidden.status_code == 403
    finally:
        client.close()
        app.dependency_overrides.clear()
