"""CLI 入口；所有动作仅做研究分析。"""
import argparse
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository
from app.data.market_provider import MarketService, normalize_code
from app.data.tushare_provider import TushareProvider
from app.data.akshare_provider import AKShareProvider

def bootstrap():
    settings = load_settings()
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.FileHandler(settings.path(f"logs/stock_agent_{stamp}.log"), encoding="utf-8"), logging.StreamHandler()])
    repository = Repository(create_db(settings.path("data/stock_agent.db")))
    return settings, repository

def main() -> None:
    parser = argparse.ArgumentParser(description="个人 A 股每日分析 Agent")
    parser.add_argument("command", choices=["init-db", "download"], default="download", nargs="?")
    parser.add_argument("code", nargs="?", default="603283.SH")
    args = parser.parse_args()
    settings, repository = bootstrap()
    if args.command == "init-db":
        print("SQLite 已初始化")
        return
    frame, warnings = MarketService([TushareProvider(), AKShareProvider()], repository).update(normalize_code(args.code))
    result = {"bars": len(frame), "latest": None if frame.empty else frame.iloc[-1]["date"], "warnings": warnings, "minimum_met": len(frame) >= 250}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if frame.empty:
        raise SystemExit(2)
if __name__ == "__main__":
    main()
