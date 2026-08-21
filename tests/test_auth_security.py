import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.db import Database
from app.security import (
    create_refresh_token,
    generate_totp_secret,
    hash_token,
    totp_code,
    validate_password_policy,
    verify_totp,
)


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


def test_refresh_token_hash_and_revoke(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_db()
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


def test_lock_revokes_refresh_tokens(tmp_path):
    db = Database(str(tmp_path / "lock.db"))
    db.init_db()
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


def test_phone_verification_code_flow(tmp_path):
    db = Database(str(tmp_path / "phone.db"))
    db.init_db()
    db.save_verification_code(
        "13800000000", "register", "123456", "2099-01-01T00:00:00+00:00"
    )
    row = db.get_verification_code("13800000000", "register")
    assert row and row["code"] == "123456"
    db.mark_code_used(row["id"])
    assert db.get_verification_code("13800000000", "register") is None


def test_new_database_has_no_default_admin(tmp_path):
    db = Database(str(tmp_path / "secure.db"))
    db.init_db()
    assert db.get_user_by_username("admin") is None
    assert db.get_user_by_username("demo") is None
    cols = {row["name"] for row in db.query_all("PRAGMA table_info(users)")}
    assert {
        "email",
        "email_verified",
        "phone",
        "phone_verified",
        "totp_secret",
        "must_change_password",
    } <= cols
    tables = {
        row["name"]
        for row in db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert "refresh_tokens" in tables
    assert "login_audit" in tables
