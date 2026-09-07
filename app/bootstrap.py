from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.settings import Settings, load_settings
from app.database.db import create_db
from app.database.migrations import migrate
from app.database.repository import Repository

DEFAULT_POSITION = {"code": "603283.SH", "max_shares": 1000, "buys": [{"price": 50, "shares": 200}, {"price": 48, "shares": 200}], "sells": []}


def bootstrap(root: Path | None = None) -> tuple[Settings, Repository]:
    root = root or Path(__file__).resolve().parents[1]
    for name in ("data", "logs", "reports", "backup", "config"):
        (root / name).mkdir(parents=True, exist_ok=True)
    defaults = root / "app/config"
    for name in ("config.yaml", "position_strategy.yaml"):
        target = root / "config" / name
        if not target.exists():
            shutil.copy2(defaults / name, target)
    position = root / "data/portfolio.json"
    if not position.exists():
        position.write_text(json.dumps(DEFAULT_POSITION, ensure_ascii=False, indent=2), encoding="utf-8")
    settings = load_settings(root)
    engine = create_db(root / "data/stock_agent.db")
    migrate(engine, root / "VERSION")
    repository = Repository(engine)
    status = {"initialized_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "pid": os.getpid(), "schema_version": 1}
    (root / "data/system_status.json").write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    return settings, repository
