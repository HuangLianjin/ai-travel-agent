"""SQLite 存储层：用户、行程、攻略、审核、审计与社区数据。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings
from app.security import hash_password, verify_password


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_offset(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(
        timespec="seconds"
    )


class Database:
    def __init__(self, db_path: str) -> None:
        self._path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    # ==================== 基础执行 ====================

    def execute(self, sql: str, params: tuple = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur.lastrowid

    def query_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict | None:
        rows = self.query_all(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ==================== 初始化 ====================

    def init_db(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trips (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    city TEXT NOT NULL,
                    params TEXT NOT NULL,
                    itinerary TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS itinerary_versions (
                    id TEXT PRIMARY KEY,
                    trip_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    summary TEXT NOT NULL,
                    plan TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]',
                    last_trip_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guides (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    city TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'user',
                    status TEXT NOT NULL DEFAULT 'pending',
                    likes INTEGER NOT NULL DEFAULT 0,
                    favorites INTEGER NOT NULL DEFAULT 0,
                    views INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id TEXT PRIMARY KEY,
                    guide_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS likes (
                    guide_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guide_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS favorites (
                    guide_id TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    PRIMARY KEY (guide_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS follows (
                    follower_id INTEGER NOT NULL,
                    followee_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (follower_id, followee_id)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    summary TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    decision_note TEXT NOT NULL DEFAULT '',
                    reviewer_id INTEGER,
                    created_at TEXT NOT NULL,
                    decided_at TEXT
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL DEFAULT '',
                    target_id TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refresh_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    token_hash TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS login_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    success INTEGER NOT NULL DEFAULT 0,
                    ip TEXT NOT NULL DEFAULT '',
                    user_agent TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recommend_slots (
                    slot TEXT PRIMARY KEY,
                    guide_id TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    session_id TEXT NOT NULL DEFAULT '',
                    intent TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    user_input TEXT NOT NULL DEFAULT '',
                    plan TEXT NOT NULL DEFAULT '{}',
                    response TEXT NOT NULL DEFAULT '',
                    agent_results TEXT NOT NULL DEFAULT '[]',
                    tool_calls TEXT NOT NULL DEFAULT '[]',
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    latency_ms INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS place_prices (
                    id TEXT PRIMARY KEY,
                    place_name TEXT NOT NULL,
                    city TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'reference',
                    source_url TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'approved',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS price_feedback (
                    id TEXT PRIMARY KEY,
                    place_name TEXT NOT NULL,
                    city TEXT NOT NULL DEFAULT '',
                    price REAL NOT NULL DEFAULT 0,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewer_id INTEGER,
                    decided_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()
            cursor = self._conn.execute("PRAGMA table_info(conversations)")
            columns = {row["name"] for row in cursor.fetchall()}
            if "last_trip_id" not in columns:
                self._conn.execute(
                    "ALTER TABLE conversations ADD COLUMN last_trip_id TEXT DEFAULT ''"
                )
                self._conn.commit()
            guide_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(guides)")
            }
            for col, ddl in (
                ("trip_id", "TEXT NOT NULL DEFAULT ''"),
                ("images", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if col not in guide_cols:
                    self._conn.execute(f"ALTER TABLE guides ADD COLUMN {col} {ddl}")
                    self._conn.commit()
            user_cols = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(users)")
            }
            for col, ddl in (
                ("nickname", "TEXT NOT NULL DEFAULT ''"),
                ("avatar", "TEXT NOT NULL DEFAULT ''"),
                ("email", "TEXT NOT NULL DEFAULT ''"),
                ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
                ("verification_code", "TEXT NOT NULL DEFAULT ''"),
                ("verification_expires_at", "TEXT NOT NULL DEFAULT ''"),
                ("login_failed_count", "INTEGER NOT NULL DEFAULT 0"),
                ("locked_until", "TEXT NOT NULL DEFAULT ''"),
                ("must_change_password", "INTEGER NOT NULL DEFAULT 0"),
                ("totp_secret", "TEXT NOT NULL DEFAULT ''"),
                ("password_changed_at", "TEXT NOT NULL DEFAULT ''"),
                ("last_login_at", "TEXT NOT NULL DEFAULT ''"),
                ("last_login_ip", "TEXT NOT NULL DEFAULT ''"),
            ):
                if col not in user_cols:
                    self._conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
                    self._conn.commit()
            self._conn.execute(
                "DELETE FROM reviews WHERE id NOT IN ("
                "SELECT r.id FROM reviews r INNER JOIN ("
                "SELECT target_type, target_id, MAX(created_at) AS max_created "
                "FROM reviews GROUP BY target_type, target_id"
                ") m ON r.target_type = m.target_type AND r.target_id = m.target_id "
                "AND r.created_at = m.max_created)"
            )
            self._conn.commit()
            self._seed_users()

    def _seed_users(self) -> None:
        settings = get_settings()
        if settings.demo_seed_enabled and not self.get_user_by_username("demo"):
            self.create_user(
                "demo",
                "demo123",
                role="user",
                email="demo@example.com",
                email_verified=1,
            )
        demo = self.get_user_by_username("demo")
        if demo and not demo.get("email"):
            self.execute(
                "UPDATE users SET email = 'demo@example.com', email_verified = 1 "
                "WHERE id = ?",
                (demo["id"],),
            )
        admin = self.get_user_by_username("admin")
        if admin and not admin.get("email"):
            self.execute(
                "UPDATE users SET email = 'admin@example.com', email_verified = 1 "
                "WHERE id = ?",
                (admin["id"],),
            )
        if not admin and settings.admin_init_password:
            self.create_user(
                "admin",
                settings.admin_init_password,
                role="super_admin",
                email="admin@example.com",
                email_verified=1,
                must_change_password=1,
            )
        elif (
            admin
            and admin.get("role") in ("admin", "super_admin")
            and verify_password("admin123", admin["password_hash"])
        ):
            self.execute(
                "UPDATE users SET must_change_password = 1 WHERE id = ?",
                (admin["id"],),
            )

    # ==================== 用户 ====================

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        email: str = "",
        email_verified: int = 0,
        must_change_password: int = 0,
    ) -> int:
        return self.execute(
            "INSERT INTO users (username, password_hash, role, status, created_at, "
            "email, email_verified, must_change_password) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?, ?)",
            (
                username,
                hash_password(password),
                role,
                _now(),
                email,
                email_verified,
                must_change_password,
            ),
        )

    def get_user_by_username(self, username: str) -> dict | None:
        return self.query_one("SELECT * FROM users WHERE username = ?", (username,))

    def get_user_by_email(self, email: str) -> dict | None:
        return self.query_one(
            "SELECT * FROM users WHERE email = ? AND email != ''",
            (email.lower(),),
        )

    def get_user_by_id(self, user_id: int) -> dict | None:
        return self.query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    def list_users(self) -> list[dict]:
        return self.query_all(
            "SELECT id, username, role, status, created_at FROM users ORDER BY id DESC"
        )

    def set_user_status(self, user_id: int, status: str) -> None:
        self.execute(
            "UPDATE users SET status = ? WHERE id = ?", (status, user_id)
        )

    def set_user_role(self, user_id: int, role: str) -> None:
        self.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def set_email_verified(self, user_id: int) -> None:
        self.execute(
            "UPDATE users SET email_verified = 1 WHERE id = ?", (user_id,)
        )

    def set_verification_code(self, user_id: int, code: str, expires_at: str) -> None:
        self.execute(
            "UPDATE users SET verification_code = ?, verification_expires_at = ? "
            "WHERE id = ?",
            (code, expires_at, user_id),
        )

    def record_login_failure(self, username: str) -> int:
        user = self.get_user_by_username(username)
        if not user:
            return 0
        settings = get_settings()
        count = int(user.get("login_failed_count") or 0) + 1
        locked_until = ""
        if count >= settings.max_login_failures:
            locked_until = _now_offset(settings.login_lock_minutes)
            count = 0
        self.execute(
            "UPDATE users SET login_failed_count = ?, locked_until = ? WHERE id = ?",
            (count, locked_until, user["id"]),
        )
        return count

    def reset_login_failures(self, user_id: int) -> None:
        self.execute(
            "UPDATE users SET login_failed_count = 0, locked_until = '' WHERE id = ?",
            (user_id,),
        )

    def update_password(self, user_id: int, password_hash: str) -> None:
        self.execute(
            "UPDATE users SET password_hash = ?, password_changed_at = ?, "
            "must_change_password = 0, verification_code = '', "
            "verification_expires_at = '' WHERE id = ?",
            (password_hash, _now(), user_id),
        )

    def set_must_change_password(self, user_id: int, value: int) -> None:
        self.execute(
            "UPDATE users SET must_change_password = ? WHERE id = ?",
            (value, user_id),
        )

    def set_totp_secret(self, user_id: int, secret: str) -> None:
        self.execute(
            "UPDATE users SET totp_secret = ? WHERE id = ?", (secret, user_id)
        )

    def set_last_login(self, user_id: int, ip: str) -> None:
        self.execute(
            "UPDATE users SET last_login_at = ?, last_login_ip = ? WHERE id = ?",
            (_now(), ip, user_id),
        )

    def create_refresh_token(
        self, user_id: int, token_hash: str, expires_at: str
    ) -> int:
        return self.execute(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, token_hash, expires_at, _now()),
        )

    def get_refresh_token(self, token_hash: str) -> dict | None:
        return self.query_one(
            "SELECT * FROM refresh_tokens WHERE token_hash = ? AND revoked = 0",
            (token_hash,),
        )

    def revoke_refresh_token(self, token_hash: str) -> None:
        self.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE token_hash = ?",
            (token_hash,),
        )

    def revoke_all_user_refresh_tokens(self, user_id: int) -> None:
        self.execute(
            "UPDATE refresh_tokens SET revoked = 1 WHERE user_id = ?", (user_id,)
        )

    def record_login_audit(
        self,
        username: str,
        success: bool,
        ip: str = "",
        user_agent: str = "",
        detail: str = "",
    ) -> None:
        self.execute(
            "INSERT INTO login_audit (username, success, ip, user_agent, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (username, 1 if success else 0, ip, user_agent, detail, _now()),
        )

    def list_login_audit(self, limit: int = 200) -> list[dict]:
        return self.query_all(
            "SELECT * FROM login_audit ORDER BY id DESC LIMIT ?", (limit,)
        )

    def update_user_profile(
        self, user_id: int, nickname: str | None = None, avatar: str | None = None
    ) -> None:
        current = self.query_one(
            "SELECT nickname, avatar FROM users WHERE id = ?", (user_id,)
        ) or {}
        self.execute(
            "UPDATE users SET nickname = ?, avatar = ? WHERE id = ?",
            (
                current.get("nickname", "") if nickname is None else nickname,
                current.get("avatar", "") if avatar is None else avatar,
                user_id,
            ),
        )

    def get_user_profile(
        self, user_id: int, viewer_id: int | None = None
    ) -> dict | None:
        user = self.query_one(
            "SELECT id, username, nickname, avatar, email_verified, totp_secret "
            "FROM users WHERE id = ?",
            (user_id,),
        )
        if not user:
            return None
        following = self.query_one(
            "SELECT COUNT(*) AS n FROM follows WHERE follower_id = ?", (user_id,)
        )["n"]
        followers = self.query_one(
            "SELECT COUNT(*) AS n FROM follows WHERE followee_id = ?", (user_id,)
        )["n"]
        is_following = bool(
            viewer_id
            and viewer_id != user_id
            and self.query_one(
                "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
                (viewer_id, user_id),
            )
        )
        result = {
            **user,
            "nickname": user.get("nickname") or user.get("username") or "",
            "following_count": following,
            "followers_count": followers,
            "is_following": is_following,
            "email_verified": bool(user.get("email_verified")),
            "totp_enabled": bool(user.get("totp_secret")) if viewer_id == user_id else False,
        }
        result.pop("totp_secret", None)
        return result

    def follow_user(self, follower_id: int, followee_id: int, follow: bool) -> None:
        if follow:
            self.execute(
                "INSERT OR IGNORE INTO follows (follower_id, followee_id, created_at) "
                "VALUES (?, ?, ?)",
                (follower_id, followee_id, _now()),
            )
        else:
            self.execute(
                "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            )

    def is_following(self, follower_id: int, followee_id: int) -> bool:
        return bool(
            self.query_one(
                "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?",
                (follower_id, followee_id),
            )
        )

    # ==================== 行程 ====================

    def create_trip(
        self, user_id: int, title: str, city: str, params: dict, itinerary: dict
    ) -> str:
        trip_id = uuid.uuid4().hex[:12]
        now = _now()
        self.execute(
            "INSERT INTO trips (id, user_id, title, city, params, itinerary, "
            "version, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, 'draft', ?, ?)",
            (
                trip_id,
                user_id,
                title,
                city,
                json.dumps(params, ensure_ascii=False),
                json.dumps(itinerary, ensure_ascii=False),
                now,
                now,
            ),
        )
        self.save_version(trip_id, 1, itinerary.get("summary", ""), itinerary)
        return trip_id

    def get_trip(self, trip_id: str, user_id: int | None = None) -> dict | None:
        row = (
            self.query_one("SELECT * FROM trips WHERE id = ?", (trip_id,))
            if user_id is None
            else self.query_one(
                "SELECT * FROM trips WHERE id = ? AND user_id = ?",
                (trip_id, user_id),
            )
        )
        return self._decode_trip(row)

    @staticmethod
    def _decode_trip(row: dict | None) -> dict | None:
        if not row:
            return None
        row = dict(row)
        row["params"] = json.loads(row.get("params") or "{}")
        row["itinerary"] = json.loads(row.get("itinerary") or "{}")
        return row

    def list_trips(self, user_id: int) -> list[dict]:
        rows = self.query_all(
            "SELECT * FROM trips WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [self._decode_trip(r) for r in rows]

    def paginate_trips(
        self, user_id: int, page: int = 1, page_size: int = 6
    ) -> dict:
        total = self.query_one(
            "SELECT COUNT(*) AS n FROM trips WHERE user_id = ?", (user_id,)
        )["n"]
        page = max(1, int(page))
        page_size = max(1, min(20, int(page_size)))
        offset = (page - 1) * page_size
        rows = self.query_all(
            "SELECT * FROM trips WHERE user_id = ? "
            "ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (user_id, page_size, offset),
        )
        return {
            "items": [self._decode_trip(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size or 1,
        }

    def update_trip(
        self,
        trip_id: str,
        version: int,
        params: dict,
        itinerary: dict,
        status: str | None = None,
        title: str | None = None,
        city: str | None = None,
    ) -> None:
        current = self.get_trip(trip_id)
        if not current:
            return
        final_status = status or current["status"]
        if title:
            self.execute(
                "UPDATE trips SET title = ?, city = ?, params = ?, itinerary = ?, version = ?, "
                "status = ?, updated_at = ? WHERE id = ?",
                (
                    title,
                    city or current["city"],
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(itinerary, ensure_ascii=False),
                    version,
                    final_status,
                    _now(),
                    trip_id,
                ),
            )
        else:
            self.execute(
                "UPDATE trips SET params = ?, itinerary = ?, version = ?, "
                "status = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(params, ensure_ascii=False),
                    json.dumps(itinerary, ensure_ascii=False),
                    version,
                    final_status,
                    _now(),
                    trip_id,
                ),
            )
        self.save_version(
            trip_id, version, itinerary.get("summary", ""), itinerary
        )

    def save_version(
        self, trip_id: str, version: int, summary: str, plan: dict
    ) -> None:
        self.execute(
            "INSERT INTO itinerary_versions (id, trip_id, version, summary, plan, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                uuid.uuid4().hex[:12],
                trip_id,
                version,
                summary,
                json.dumps(plan, ensure_ascii=False),
                _now(),
            ),
        )

    def list_versions(self, trip_id: str) -> list[dict]:
        return self.query_all(
            "SELECT version, summary, plan, created_at FROM itinerary_versions "
            "WHERE trip_id = ? ORDER BY version DESC",
            (trip_id,),
        )

    def delete_trip(self, trip_id: str, user_id: int) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM trips WHERE id = ? AND user_id = ?",
                (trip_id, user_id),
            )
            if cursor.rowcount == 0:
                self._conn.commit()
                return False
            self._conn.execute(
                "DELETE FROM itinerary_versions WHERE trip_id = ?", (trip_id,)
            )
            self._conn.execute(
                "DELETE FROM reviews WHERE target_type = 'trip' AND target_id = ?",
                (trip_id,),
            )
            self._conn.commit()
            return True

    # ==================== 会话 ====================

    def get_conversation(self, session_id: str, user_id: int) -> dict | None:
        return self.query_one(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )

    def get_last_trip_id(self, session_id: str, user_id: int) -> str:
        row = self.query_one(
            "SELECT last_trip_id FROM conversations WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        return (row or {}).get("last_trip_id", "") or ""

    def set_last_trip_id(self, session_id: str, user_id: int, trip_id: str) -> None:
        existing = self.get_conversation(session_id, user_id)
        if existing:
            self.execute(
                "UPDATE conversations SET last_trip_id = ?, updated_at = ? WHERE id = ?",
                (trip_id, _now(), session_id),
            )
        else:
            now = _now()
            self.execute(
                "INSERT OR IGNORE INTO conversations "
                "(id, user_id, messages, last_trip_id, created_at, updated_at) "
                "VALUES (?, ?, '[]', ?, ?, ?)",
                (session_id, user_id, trip_id, now, now),
            )
            self.execute(
                "UPDATE conversations SET last_trip_id = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (trip_id, now, session_id, user_id),
            )

    def upsert_conversation(self, session_id: str, user_id: int, messages: list) -> None:
        existing = self.get_conversation(session_id, user_id)
        if existing:
            self.execute(
                "UPDATE conversations SET messages = ?, updated_at = ? WHERE id = ?",
                (json.dumps(messages, ensure_ascii=False), _now(), session_id),
            )
        else:
            now = _now()
            self.execute(
                "INSERT OR IGNORE INTO conversations "
                "(id, user_id, messages, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    json.dumps(messages, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            self.execute(
                "UPDATE conversations SET messages = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ?",
                (json.dumps(messages, ensure_ascii=False), now, session_id, user_id),
            )

    # ==================== Agent 运行追踪 ====================

    def save_agent_run(
        self,
        run_id: str,
        user_id: int,
        session_id: str,
        intent: str,
        status: str,
        user_input: str,
        plan: dict,
        response: str,
        agent_results: list,
        tool_calls: list,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        error: str = "",
    ) -> None:
        self.execute(
            "INSERT INTO agent_runs (run_id, user_id, session_id, intent, status, "
            "user_input, plan, response, agent_results, tool_calls, prompt_tokens, "
            "completion_tokens, latency_ms, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                user_id,
                session_id,
                intent,
                status,
                user_input[:4000],
                json.dumps(plan, ensure_ascii=False),
                response[:6000],
                json.dumps(agent_results, ensure_ascii=False),
                json.dumps(tool_calls, ensure_ascii=False),
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(latency_ms or 0),
                error[:2000],
                _now(),
            ),
        )

    def list_agent_runs(
        self, user_id: int | None = None, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        if user_id is not None:
            rows = self.query_all(
                "SELECT run_id, user_id, session_id, intent, status, prompt_tokens, "
                "completion_tokens, latency_ms, created_at FROM agent_runs "
                "WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            )
        else:
            rows = self.query_all(
                "SELECT run_id, user_id, session_id, intent, status, prompt_tokens, "
                "completion_tokens, latency_ms, created_at FROM agent_runs "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return rows

    def agent_run_summary(self) -> dict:
        total = self.query_one(
            "SELECT COUNT(*) AS n, "
            "COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens), 0) AS completion_tokens, "
            "COALESCE(AVG(latency_ms), 0) AS avg_latency_ms "
            "FROM agent_runs"
        ) or {}
        by_status = self.query_all(
            "SELECT status, COUNT(*) AS n FROM agent_runs GROUP BY status"
        )
        by_intent = self.query_all(
            "SELECT intent, COUNT(*) AS n FROM agent_runs GROUP BY intent"
        )
        n = int(total.get("n") or 0)
        success = next(
            (int(r["n"]) for r in by_status if r.get("status") == "success"), 0
        )
        failed = next(
            (int(r["n"]) for r in by_status if r.get("status") == "failed"), 0
        )
        prompt = int(total.get("prompt_tokens") or 0)
        completion = int(total.get("completion_tokens") or 0)
        latency_rows = self.query_all("SELECT latency_ms FROM agent_runs")
        latencies = sorted(int(r.get("latency_ms") or 0) for r in latency_rows)
        p95 = (
            latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
            if latencies
            else 0
        )
        return {
            "total_runs": n,
            "success_runs": success,
            "failed_runs": failed,
            "success_rate": round(success / n, 4) if n else 0.0,
            "avg_latency_ms": round(float(total.get("avg_latency_ms") or 0), 2),
            "p95_latency_ms": p95,
            "total_tokens": prompt + completion,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "by_status": by_status,
            "by_intent": by_intent,
        }

    # ==================== 社区 ====================

    def create_guide(
        self,
        user_id: int,
        title: str,
        city: str,
        content: str,
        source: str = "user",
        trip_id: str = "",
        images: list | None = None,
    ) -> str:
        guide_id = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO guides (id, user_id, title, city, content, source, trip_id, images, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                guide_id,
                user_id,
                title,
                city,
                content,
                source,
                trip_id,
                json.dumps(images or [], ensure_ascii=False),
                _now(),
            ),
        )
        return guide_id

    def update_guide_images(self, guide_id: str, images: list) -> None:
        self.execute(
            "UPDATE guides SET images = ? WHERE id = ?",
            (json.dumps(images or [], ensure_ascii=False), guide_id),
        )

    @staticmethod
    def _decode_guide(row: dict | None) -> dict | None:
        if not row:
            return None
        row = dict(row)
        try:
            row["images"] = json.loads(row.get("images") or "[]")
        except Exception:
            row["images"] = []
        return row

    def get_guide(self, guide_id: str) -> dict | None:
        row = self.query_one("SELECT * FROM guides WHERE id = ?", (guide_id,))
        return self._decode_guide(row) if row else None

    def list_guides(
        self,
        status: str | None = None,
        include_user: bool = False,
        user_id: int | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM guides"
        params: tuple = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY created_at DESC"
        rows = [self._decode_guide(r) for r in self.query_all(sql, params)]
        if include_user:
            users = {
                u["id"]: u["username"]
                for u in self.query_all("SELECT id, username FROM users")
            }
            for row in rows:
                row["username"] = users.get(row["user_id"], "unknown")
        if user_id is not None:
            liked = {
                r["guide_id"]
                for r in self.query_all(
                    "SELECT guide_id FROM likes WHERE user_id = ?", (user_id,)
                )
            }
            favorited = {
                r["guide_id"]
                for r in self.query_all(
                    "SELECT guide_id FROM favorites WHERE user_id = ?", (user_id,)
                )
            }
            for row in rows:
                row["liked_by_me"] = row["id"] in liked
                row["favorited_by_me"] = row["id"] in favorited
        return rows

    def paginate_guides(
        self,
        status: str | None = None,
        user_id: int | None = None,
        page: int = 1,
        page_size: int = 10,
        city: str = "",
        keyword: str = "",
        sort: str = "hot",
    ) -> dict:
        conditions: list[str] = []
        params: list[Any] = []
        if status:
            conditions.append("g.status = ?")
            params.append(status)
        if city:
            conditions.append("g.city LIKE ?")
            params.append(f"%{city}%")
        if keyword:
            conditions.append("(g.title LIKE ? OR g.content LIKE ?)")
            params.append(f"%{keyword}%")
            params.append(f"%{keyword}%")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = self.query_one(
            f"SELECT COUNT(*) AS n FROM guides g {where}", tuple(params)
        )["n"]
        page = max(1, int(page))
        page_size = max(1, min(20, int(page_size)))
        offset = (page - 1) * page_size
        if sort == "hot":
            order_by = (
                "(g.likes * 3 + g.favorites * 5 + "
                "(SELECT COUNT(*) FROM comments c WHERE c.guide_id = g.id) * 2 "
                "+ g.views * 0.1) DESC, g.created_at DESC"
            )
        else:
            order_by = "g.created_at DESC"
        rows = [
            self._decode_guide(r)
            for r in self.query_all(
                f"SELECT g.* FROM guides g {where} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                tuple(params + [page_size, offset]),
            )
        ]
        users = {
            u["id"]: u["username"]
            for u in self.query_all("SELECT id, username FROM users")
        }
        liked = (
            {
                r["guide_id"]
                for r in self.query_all(
                    "SELECT guide_id FROM likes WHERE user_id = ?", (user_id,)
                )
            }
            if user_id is not None
            else set()
        )
        favorited = (
            {
                r["guide_id"]
                for r in self.query_all(
                    "SELECT guide_id FROM favorites WHERE user_id = ?", (user_id,)
                )
            }
            if user_id is not None
            else set()
        )
        for row in rows:
            row["username"] = users.get(row["user_id"], "unknown")
            row["liked_by_me"] = row["id"] in liked
            row["favorited_by_me"] = row["id"] in favorited
        pages = (total + page_size - 1) // page_size or 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def paginate_liked_guides(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 6,
    ) -> dict:
        total = self.query_one(
            "SELECT COUNT(*) AS n FROM likes WHERE user_id = ?", (user_id,)
        )["n"]
        page = max(1, int(page))
        page_size = max(1, min(20, int(page_size)))
        offset = (page - 1) * page_size
        rows = [
            self._decode_guide(r)
            for r in self.query_all(
                "SELECT g.* FROM guides g JOIN likes l ON l.guide_id = g.id "
                "WHERE l.user_id = ? ORDER BY g.created_at DESC LIMIT ? OFFSET ?",
                (user_id, page_size, offset),
            )
        ]
        pages = (total + page_size - 1) // page_size or 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def paginate_my_guides(
        self,
        user_id: int,
        page: int = 1,
        page_size: int = 6,
    ) -> dict:
        total = self.query_one(
            "SELECT COUNT(*) AS n FROM guides WHERE user_id = ?", (user_id,)
        )["n"]
        page = max(1, int(page))
        page_size = max(1, min(20, int(page_size)))
        offset = (page - 1) * page_size
        rows = [
            self._decode_guide(r)
            for r in self.query_all(
                "SELECT * FROM guides WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, page_size, offset),
            )
        ]
        pages = (total + page_size - 1) // page_size or 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def update_guide_status(
        self, guide_id: str, status: str, note: str = ""
    ) -> None:
        self.execute(
            "UPDATE guides SET status = ? WHERE id = ?", (status, guide_id)
        )
        guide = self.get_guide(guide_id)
        if guide:
            self.create_review(
                "guide",
                guide_id,
                status,
                guide["title"],
                guide,
                note=note,
            )

    def like_guide(self, guide_id: str, user_id: int, liked: bool) -> None:
        if liked:
            self.execute(
                "INSERT OR IGNORE INTO likes (guide_id, user_id) VALUES (?, ?)",
                (guide_id, user_id),
            )
        else:
            self.execute(
                "DELETE FROM likes WHERE guide_id = ? AND user_id = ?",
                (guide_id, user_id),
            )
        self._refresh_guide_counts(guide_id)

    def favorite_guide(self, guide_id: str, user_id: int, favorited: bool) -> None:
        if favorited:
            self.execute(
                "INSERT OR IGNORE INTO favorites (guide_id, user_id) VALUES (?, ?)",
                (guide_id, user_id),
            )
        else:
            self.execute(
                "DELETE FROM favorites WHERE guide_id = ? AND user_id = ?",
                (guide_id, user_id),
            )
        self._refresh_guide_counts(guide_id)

    def _refresh_guide_counts(self, guide_id: str) -> None:
        likes = self.query_one(
            "SELECT COUNT(*) AS n FROM likes WHERE guide_id = ?", (guide_id,)
        )["n"]
        favorites = self.query_one(
            "SELECT COUNT(*) AS n FROM favorites WHERE guide_id = ?", (guide_id,)
        )["n"]
        self.execute(
            "UPDATE guides SET likes = ?, favorites = ? WHERE id = ?",
            (likes, favorites, guide_id),
        )

    def add_comment(self, guide_id: str, user_id: int, content: str) -> str:
        comment_id = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO comments (id, guide_id, user_id, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (comment_id, guide_id, user_id, content, _now()),
        )
        return comment_id

    def list_comments(self, guide_id: str) -> list[dict]:
        return self.query_all(
            "SELECT * FROM comments WHERE guide_id = ? ORDER BY created_at ASC",
            (guide_id,),
        )

    def paginate_favorites(
        self, user_id: int, page: int = 1, page_size: int = 6
    ) -> dict:
        total = self.query_one(
            "SELECT COUNT(*) AS n FROM favorites WHERE user_id = ?", (user_id,)
        )["n"]
        page = max(1, int(page))
        page_size = max(1, min(20, int(page_size)))
        offset = (page - 1) * page_size
        rows = [
            self._decode_guide(r)
            for r in self.query_all(
                "SELECT g.* FROM guides g JOIN favorites f ON f.guide_id = g.id "
                "WHERE f.user_id = ? ORDER BY g.created_at DESC LIMIT ? OFFSET ?",
                (user_id, page_size, offset),
            )
        ]
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": (total + page_size - 1) // page_size or 1,
        }

    # ==================== 审核 ====================

    def create_review(
        self,
        target_type: str,
        target_id: str,
        status: str,
        summary: str,
        payload: dict,
        note: str = "",
        reviewer_id: int | None = None,
    ) -> str:
        review_id = uuid.uuid4().hex[:12]
        now = _now()
        self.execute(
            "INSERT INTO reviews (id, target_type, target_id, status, summary, "
            "payload, decision_note, reviewer_id, created_at, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                review_id,
                target_type,
                target_id,
                status,
                summary,
                json.dumps(payload, ensure_ascii=False),
                note,
                reviewer_id,
                now,
                now if status != "pending" else "",
            ),
        )
        return review_id

    def create_review_if_missing(
        self,
        target_type: str,
        target_id: str,
        status: str,
        summary: str,
        payload: dict,
        note: str = "",
        reviewer_id: int | None = None,
    ) -> str:
        existing = self.query_one(
            "SELECT id FROM reviews WHERE target_type = ? AND target_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (target_type, target_id),
        )
        if existing:
            return existing["id"]
        return self.create_review(
            target_type,
            target_id,
            status,
            summary,
            payload,
            note=note,
            reviewer_id=reviewer_id,
        )

    def list_place_prices(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM place_prices"
        if status:
            sql += " WHERE status = ?"
        sql += " ORDER BY updated_at DESC"
        rows = self.query_all(sql, (status,) if status else ())
        for row in rows:
            row["price"] = float(row.get("price") or 0)
        return rows

    def upsert_place_price(
        self,
        place_name: str,
        city: str,
        price: float,
        source: str = "reference",
        source_url: str = "",
        note: str = "",
        status: str = "approved",
    ) -> str:
        now = _now()
        existing = self.query_one(
            "SELECT id FROM place_prices WHERE place_name = ? AND city = ? "
            "ORDER BY updated_at DESC LIMIT 1",
            (place_name, city),
        )
        if existing:
            self.execute(
                "UPDATE place_prices SET price = ?, source = ?, source_url = ?, "
                "note = ?, status = ?, updated_at = ? WHERE id = ?",
                (float(price), source, source_url, note, status, now, existing["id"]),
            )
            return existing["id"]
        price_id = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO place_prices (id, place_name, city, price, source, "
            "source_url, note, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                price_id,
                place_name,
                city,
                float(price),
                source,
                source_url,
                note,
                status,
                now,
                now,
            ),
        )
        return price_id

    def delete_place_price(self, price_id: str) -> bool:
        return self.execute(
            "DELETE FROM place_prices WHERE id = ?", (price_id,)
        ) > 0

    def submit_price_feedback(
        self,
        place_name: str,
        city: str,
        price: float,
        user_id: int,
    ) -> str:
        feedback_id = uuid.uuid4().hex[:12]
        self.execute(
            "INSERT INTO price_feedback (id, place_name, city, price, user_id, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (
                feedback_id,
                place_name,
                city,
                float(price),
                user_id,
                _now(),
            ),
        )
        return feedback_id

    def list_price_feedback(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM price_feedback"
        if status:
            sql += " WHERE status = ?"
        sql += " ORDER BY created_at DESC"
        rows = self.query_all(sql, (status,) if status else ())
        for row in rows:
            row["price"] = float(row.get("price") or 0)
        return rows

    def decide_price_feedback(
        self,
        feedback_id: str,
        status: str,
        reviewer_id: int,
    ) -> bool:
        row = self.query_one(
            "SELECT * FROM price_feedback WHERE id = ?", (feedback_id,)
        )
        if not row or row.get("status") != "pending":
            return False
        if status == "approved":
            self.upsert_place_price(
                row["place_name"],
                row["city"],
                float(row["price"] or 0),
                source="用户反馈",
                note=f"用户反馈价格 {row['price']} 元，已审核",
            )
        self.execute(
            "UPDATE price_feedback SET status = ?, reviewer_id = ?, decided_at = ? "
            "WHERE id = ?",
            (status, reviewer_id, _now(), feedback_id),
        )
        return True

    def list_reviews(
        self,
        status: str | None = None,
        target_type: str | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM reviews"
        params: list[Any] = []
        conditions: list[str] = []
        if status:
            conditions.append("status = ?")
            params.append(status)
        if target_type:
            conditions.append("target_type = ?")
            params.append(target_type)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        return self.query_all(sql, tuple(params))

    def decide_review(
        self,
        review_id: str,
        status: str,
        note: str,
        reviewer_id: int,
    ) -> bool:
        cur = self.execute(
            "UPDATE reviews SET status = ?, decision_note = ?, reviewer_id = ?, "
            "decided_at = ? WHERE id = ? AND status = 'pending'",
            (status, note, reviewer_id, _now(), review_id),
        )
        return cur > 0

    # ==================== 审计与推荐位 ====================

    def audit(
        self,
        user_id: int | None,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: str = "",
    ) -> None:
        self.execute(
            "INSERT INTO audit_logs (user_id, action, target_type, target_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action, target_type, target_id, detail, _now()),
        )

    def list_audit_logs(self, limit: int = 100) -> list[dict]:
        return self.query_all(
            "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
        )

    def set_recommend_slot(self, slot: str, guide_id: str, enabled: bool) -> None:
        self.execute(
            "INSERT INTO recommend_slots (slot, guide_id, enabled, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(slot) DO UPDATE SET "
            "guide_id = excluded.guide_id, enabled = excluded.enabled, "
            "updated_at = excluded.updated_at",
            (slot, guide_id, 1 if enabled else 0, _now()),
        )

    def list_recommend_slots(self) -> list[dict]:
        return self.query_all(
            "SELECT * FROM recommend_slots ORDER BY slot ASC"
        )

