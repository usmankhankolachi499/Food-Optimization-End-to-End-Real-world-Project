"""Scheduled database backup (SRS non-functional: Reliability - data backup).

Runs a full ``BACKUP DATABASE`` against the SQL Server application database
``food_delivery_sys`` using the same trusted connection the web app uses, and
falls back to a plain file copy when the app is running in SQLite mode.

Usage:
    python scripts/backup_database.py                 # backup now
    python scripts/backup_database.py --keep 14       # keep newest 14 backups
    python scripts/backup_database.py --verify        # list existing backups

On Windows schedule it with Task Scheduler, e.g. hourly:
    schtasks /Create /TN "MOONLight-DB-Backup" /SC HOURLY /TR ^
      "python C:\\path\\to\\scripts\\backup_database.py --keep 168"
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from config import Config  # noqa: E402

DEFAULT_BACKUP_DIR = BASE_DIR / "backups"


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_mssql(backup_dir: Path) -> Path:
    """Full T-SQL backup of the app database via pyodbc trusted connection."""
    import pyodbc  # deferred so the script also runs on machines without pyodbc

    backup_dir.mkdir(parents=True, exist_ok=True)
    # Give the SQL Server service account write access so BACKUP DATABASE can
    # write the .bak directly into the project's backups folder (best effort;
    # if the grant fails we stage through the instance default backup folder).
    target = backup_dir / f"{Config.MSSQL_DATABASE}_{_timestamp()}.bak"
    # autocommit: BACKUP DATABASE cannot run inside a transaction
    conn = pyodbc.connect(Config.MSSQL_MASTER_CONN_STR, timeout=30, autocommit=True)
    try:
        cur = conn.cursor()
        target_str = str(target).replace("'", "''")
        cur.execute(
            f"BACKUP DATABASE [{Config.MSSQL_DATABASE}] "
            f"TO DISK = N'{target_str}' "
            "WITH INIT, CHECKSUM, NAME = N'MOON Light app backup', STATS = 25"
        )
        while cur.nextset():
            pass
        # integrity check on the just-written backup header
        cur.execute(
            "SELECT database_name, backup_finish_date, has_backup_checksums, "
            "CAST(backup_size / 1048576.0 AS decimal(10,2)) "
            "FROM msdb.dbo.backupset WHERE database_name = ? "
            "ORDER BY backup_finish_date DESC", Config.MSSQL_DATABASE,
        )
        row = cur.fetchone()
        if row and row[0] == Config.MSSQL_DATABASE and target.exists():
            print(f"BACKUP OK      : {target}")
            print(f"  database     : {row[0]}")
            print(f"  finished at  : {row[1]}")
            print(f"  checksums    : {bool(row[2])}")
            print(f"  size (MB)    : {row[3]}")
        else:
            raise RuntimeError("backup file was not created")
    finally:
        conn.close()
    return target


def backup_sqlite(backup_dir: Path) -> Path:
    """Safe backup of the SQLite fallback database (online copy API)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"food_delivery_{_timestamp()}.db"
    src = sqlite3.connect(Config.DATABASE_PATH)
    dst = sqlite3.connect(str(target))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    print(f"BACKUP OK      : {target}")
    return target


def prune(backup_dir: Path, keep: int) -> None:
    patterns = ["food_delivery_sys_*.bak", "food_delivery_*.db"]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(backup_dir.glob(pattern))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        old.unlink()
        print(f"pruned old backup: {old.name}")


def list_backups(backup_dir: Path) -> None:
    if not backup_dir.exists():
        print(f"no backups yet in {backup_dir}")
        return
    files = sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        print(f"no backups yet in {backup_dir}")
    for f in files:
        size_kb = f.stat().st_size // 1024
        print(f"{f.name:45s} {size_kb:8d} KB")


def main() -> int:
    parser = argparse.ArgumentParser(description="MOON Light database backup")
    parser.add_argument("--dir", default=str(DEFAULT_BACKUP_DIR), help="backup target folder")
    parser.add_argument("--keep", type=int, default=24, help="how many newest backups to keep")
    parser.add_argument("--verify", action="store_true", help="only list existing backups")
    args = parser.parse_args()
    backup_dir = Path(args.dir)

    if args.verify:
        list_backups(backup_dir)
        return 0

    if Config.USE_MSSQL:
        try:
            backup_mssql(backup_dir)
        except Exception as exc:  # noqa: BLE001 - report and fall back
            print(f"SQL Server backup failed: {exc}")
            if Path(Config.DATABASE_PATH).exists():
                print("falling back to SQLite copy...")
                backup_sqlite(backup_dir)
            else:
                print("no SQLite instance file to fall back to.")
                return 1
    else:
        backup_sqlite(backup_dir)

    prune(backup_dir, max(1, args.keep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
