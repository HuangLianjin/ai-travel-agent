"""审计日志快捷封装。"""

from __future__ import annotations

from app.db import Database


def audit(
    db: Database,
    user_id: int | None,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    db.audit(user_id, action, target_type, target_id, detail)
