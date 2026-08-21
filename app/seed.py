"""初始化数据库并写入演示攻略数据。"""

from __future__ import annotations

from pathlib import Path

from app.config import get_settings
from app.corpus import build_docs
from app.db import Database


def main() -> None:
    settings = get_settings()
    Path(settings.db_dir).mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    db.init_db()
    user = db.get_user_by_username("demo")
    if not user:
        print("未启用演示账号，跳过内置攻略初始化")
        db.close()
        return
    for doc in build_docs():
        title = doc.get("title") or doc.get("name", "攻略")
        existing = db.query_one(
            "SELECT id FROM guides WHERE title = ?", (title,)
        )
        if existing:
            continue
        db.create_guide(
            user["id"],
            title,
            doc.get("city", ""),
            doc.get("content", ""),
            source=doc.get("source", "内置语料"),
        )
    for guide in db.list_guides("pending")[:4]:
        db.update_guide_status(guide["id"], "approved")
    print("初始化完成")
    db.close()


if __name__ == "__main__":
    main()

