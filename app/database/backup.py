from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import zipfile


def backup_database(database: Path, directory: Path, today: date | None = None, retention_days: int = 30, prefix: str = "stock_agent") -> Path:
    today = today or date.today()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{prefix}_{today:%Y%m%d}.db"
    with sqlite3.connect(database) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    cutoff = today - timedelta(days=retention_days)
    for item in directory.glob(f"{prefix}_????????.db"):
        try:
            stamp = datetime.strptime(item.stem.removeprefix(prefix + "_"), "%Y%m%d").date()
            if stamp < cutoff:
                item.unlink()
        except ValueError:
            continue
    return target


def clean_reports(directory: Path, retention_days: int = 365, archive: bool = False, today: date | None = None) -> int:
    today = today or date.today()
    cutoff = today - timedelta(days=retention_days)
    old = []
    for item in directory.rglob("20??-??-??.*"):
        try:
            if datetime.strptime(item.stem, "%Y-%m-%d").date() < cutoff:
                old.append(item)
        except ValueError:
            continue
    if archive and old:
        archive_file = directory / f"archive_before_{cutoff:%Y%m%d}.zip"
        with zipfile.ZipFile(archive_file, "a", compression=zipfile.ZIP_DEFLATED) as bundle:
            existing = set(bundle.namelist())
            for item in old:
                name = str(item.relative_to(directory))
                if name not in existing:
                    bundle.write(item, name)
    for item in old:
        item.unlink()
    return len(old)
