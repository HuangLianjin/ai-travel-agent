"""SQLite 数据与上传文件自动备份：打包 data/ 并保留最近 14 份。"""

from __future__ import annotations

import os
import shutil
import tarfile
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
KEEP_BACKUPS = int(os.getenv("KEEP_BACKUPS", "14"))


def main() -> None:
    if not DATA_DIR.exists():
        print("NO_DATA_DIR", DATA_DIR)
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"travel-{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        tar.add(str(DATA_DIR), arcname=DATA_DIR.name)
    backups = sorted(BACKUP_DIR.glob("travel-*.tar.gz"))
    for old in backups[:-KEEP_BACKUPS] if KEEP_BACKUPS > 0 else []:
        old.unlink(missing_ok=True)
    print("BACKUP_OK", target, target.stat().st_size)


if __name__ == "__main__":
    main()