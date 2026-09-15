"""把现有 SQLite 数据迁移到 PostgreSQL。

用法：
  python scripts/migrate_sqlite_to_postgres.py --sqlite data/travel.db \
      --dsn "postgresql://travel:travel@127.0.0.1:5432/travel"

迁移前会自动建表（幂等），迁移后打印每个表的行数对比，并把自增序列推进到已有最大值。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402

TABLES = [
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
    "user_feedback",
    "place_prices",
    "price_feedback",
]

IDENTITY_SEQUENCES = [
    ("users", "id"),
    ("audit_logs", "id"),
    ("refresh_tokens", "id"),
    ("login_audit", "id"),
    ("verification_codes", "id"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description="SQLite -> PostgreSQL 数据迁移")
    parser.add_argument("--sqlite", required=True, help="SQLite 数据库文件路径")
    parser.add_argument("--dsn", default="", help="PostgreSQL 连接串，默认读 DATABASE_URL")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise SystemExit(f"SQLite 文件不存在: {sqlite_path}")

    dsn = args.dsn or get_settings().db_dsn
    src = sqlite3.connect(str(sqlite_path))
    src.row_factory = sqlite3.Row
    dst = Database(dsn)
    dst.init_db()

    for table in TABLES:
        source_table = src.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        if not source_table:
            continue
        src_cols = [
            row["name"]
            for row in src.execute(f"PRAGMA table_info({table})").fetchall()
        ]
        rows = src.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
        columns = ", ".join(src_cols)
        placeholders = ", ".join(["%s"] * len(src_cols))
        insert_sql = (
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT DO NOTHING"
        )
        for row in rows:
            dst.execute(insert_sql, tuple(row[col] for col in src_cols))
        print(f"MIGRATED {table}: {len(rows)} rows")

    for table, column in IDENTITY_SEQUENCES:
        dst.execute(
            f"SELECT setval(pg_get_serial_sequence(%s, %s), "
            f"COALESCE((SELECT MAX({column}) FROM {table}), 1))",
            (table, column),
        )

    print("\n=== 行数对比 ===")
    mismatched = 0
    for table in TABLES:
        if not src.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone():
            continue
        n_src = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        n_dst = int(dst.query_one(f"SELECT COUNT(*) AS n FROM {table}")["n"])
        status = "OK" if n_src == n_dst else "DIFF"
        if status == "DIFF":
            mismatched += 1
        print(f"{status:4} {table}: sqlite={n_src} postgres={n_dst}")

    src.close()
    dst.close()
    if mismatched:
        raise SystemExit(f"迁移完成但有 {mismatched} 张表行数不一致，请检查")
    print("\n迁移完成，全部表行数一致")


if __name__ == "__main__":
    main()
