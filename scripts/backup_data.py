"""PostgreSQL 数据与上传文件自动备份：pg_dump + 打包 uploads，保留最近 14 份。"""

from __future__ import annotations

import os
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "backups"))
KEEP_BACKUPS = int(os.getenv("KEEP_BACKUPS", "14"))
DATABASE_URL = os.getenv("DATABASE_URL", "")


def main() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = BACKUP_DIR / f"travel-{stamp}.tar.gz"
    dump = BACKUP_DIR / f"travel-{stamp}.sql"

    if DATABASE_URL:
        try:
            subprocess.run(
                [
                    "pg_dump",
                    DATABASE_URL,
                    "--no-owner",
                    "--no-privileges",
                    "-f",
                    str(dump),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            print("PG_DUMP_OK", dump)
        except FileNotFoundError:
            print("PG_DUMP_SKIP pg_dump not installed; only uploads backed up")
        except subprocess.CalledProcessError as exc:
            print("PG_DUMP_FAIL", exc.stderr[-500:] if exc.stderr else exc)

    with tarfile.open(target, "w:gz") as tar:
        if DATA_DIR.exists():
            tar.add(str(DATA_DIR), arcname=DATA_DIR.name)
        if dump.exists():
            tar.add(str(dump), arcname=dump.name)
    if dump.exists():
        dump.unlink(missing_ok=True)

    backups = sorted(BACKUP_DIR.glob("travel-*.tar.gz"))
    for old in backups[:-KEEP_BACKUPS] if KEEP_BACKUPS > 0 else []:
        old.unlink(missing_ok=True)
    print("BACKUP_OK", target, target.stat().st_size)


if __name__ == "__main__":
    main()
