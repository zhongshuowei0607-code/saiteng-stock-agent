"""CLI 入口；所有动作仅做研究分析。"""

import argparse
import json
from app.config.settings import Settings
from app.bootstrap import bootstrap as initialize
from app.database.db import create_db
from app.database.repository import Repository
from app.data.market_provider import MarketService, normalize_code
from app.data.remote_market import providers


def bootstrap() -> tuple[Settings, Repository]:
    settings, repository = initialize()
    from app.config.logging_config import configure_logging

    configure_logging(settings.root)
    return settings, repository


def main() -> None:
    parser = argparse.ArgumentParser(description="个人 A 股每日分析 Agent")
    parser.add_argument(
        "command",
        choices=["init-db", "download", "analyze", "daily", "web", "server", "migrate", "test-bark", "test-email", "backup"],
        default="web",
        nargs="?",
    )
    parser.add_argument("code", nargs="?", default="603283.SH")
    parser.add_argument("--offline", action="store_true", help="仅使用缓存且禁用 LLM")
    args = parser.parse_args()
    settings, repository = bootstrap()
    if args.command in ("web", "server"):
        import uvicorn
        from app.main import create_app

        host = "0.0.0.0" if args.command == "server" else "127.0.0.1"
        uvicorn.run(create_app(settings, repository), host=host, port=8000, workers=1)
        return
    if args.command == "migrate":
        print("数据库迁移完成")
        return
    if args.command in ("test-bark", "test-email"):
        from app.notifications import NotificationService

        notifier = NotificationService(settings.root)
        ok = notifier.bark("Stock Agent 测试", "Bark 配置有效") if args.command == "test-bark" else notifier.email("Stock Agent 测试", "Email 配置有效")
        print("发送成功" if ok else "未发送，请检查配置和 notification.log")
        raise SystemExit(0 if ok else 2)
    if args.command == "backup":
        from app.database.backup import backup_database

        target = backup_database(settings.path("data/stock_agent.db"), settings.path("backup"), retention_days=settings.config["storage"]["backup_retention_days"])
        print(f"备份完成：{target}")
        return
    if args.command == "init-db":
        print("SQLite 已初始化")
        return
    if args.command == "daily" and not args.offline:
        from app.scheduler.jobs import TradingCalendar, daily_job
        from app.analysis.stock_analyzer import StockAnalyzer
        from app.analysis.runner import AnalysisRunner

        success = daily_job(
            AnalysisRunner(StockAnalyzer(settings, repository)),
            TradingCalendar(settings.path("data/trading_calendar.json")),
        )
        print(
            "交易日任务已完成"
            if success
            else "任务未执行或失败，请查看日志；可用 analyze 显式手动分析"
        )
        return
    if args.command in ("analyze", "daily"):
        from app.analysis.stock_analyzer import StockAnalyzer

        report = StockAnalyzer(settings, repository).analyze(
            args.code, refresh=not args.offline, use_llm=not args.offline
        )
        print(
            json.dumps(
                {
                    "date": report["date"],
                    "market": report["market"],
                    "risk": report["risk"],
                    "ai_status": report["ai"]["status"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    frame, warnings = MarketService(providers(), repository).update(
        normalize_code(args.code)
    )
    result = {
        "bars": len(frame),
        "latest": None if frame.empty else frame.iloc[-1]["date"],
        "warnings": warnings,
        "minimum_met": len(frame) >= 250,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if frame.empty:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
