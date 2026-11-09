from __future__ import annotations

from pathlib import Path
from sqlalchemy import Engine, text

SCHEMA_VERSION = 2


def migrate(engine: Engine, version_file: Path) -> int:
    """以可重复执行的迁移维护现有 SQLite，升级时不要求删库。"""
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS system_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
        row = connection.execute(text("SELECT value FROM system_meta WHERE key='schema_version'")) .scalar_one_or_none()
        current = int(row or 0)
        if current < 1:
            connection.execute(text("CREATE TABLE IF NOT EXISTS trigger_states (signal TEXT PRIMARY KEY, state TEXT NOT NULL, last_triggered TEXT, updated_at TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS trigger_events (id INTEGER PRIMARY KEY AUTOINCREMENT, signal TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, secret INTEGER NOT NULL DEFAULT 0)"))
        if current < 2:
            connection.execute(text("CREATE TABLE IF NOT EXISTS adjusted_bars (code TEXT NOT NULL, date TEXT NOT NULL, payload JSON NOT NULL, PRIMARY KEY(code, date))"))
        connection.execute(text("INSERT INTO system_meta(key,value) VALUES('schema_version',:v) ON CONFLICT(key) DO UPDATE SET value=:v"), {"v": str(SCHEMA_VERSION)})
        connection.execute(text("INSERT INTO system_meta(key,value) VALUES('app_version',:v) ON CONFLICT(key) DO UPDATE SET value=:v"), {"v": version_file.read_text(encoding="utf-8").strip()})
    return SCHEMA_VERSION
