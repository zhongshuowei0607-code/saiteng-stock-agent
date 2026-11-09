"""CLI 入口；所有动作仅做研究分析。"""

import argparse
import json
from app.config.settings import Settings
from app.bootstrap import bootstrap as initialize
from app.database.db import create_db
from app.database.repository import Repository
from app.data.market_provider import MarketService, normalize_code
from app.data.remote_market import adjusted_providers, providers


def bootstrap() -> tuple[Settings, Repository]:
    settings, repository = initialize()
    from app.config.logging_config import configure_logging

    configure_logging(settings.root)
    return settings, repository


def main() -> None:
    parser = argparse.ArgumentParser(description="个人 A 股每日分析 Agent")
    parser.add_argument(
        "command",
        choices=["init-db", "download", "analyze", "backtest", "daily", "web", "server", "migrate", "test-bark", "test-email", "backup"],
        default="web",
        nargs="?",
    )
    parser.add_argument("code", nargs="?", default="603283.SH")
    parser.add_argument("--offline", action="store_true", help="仅使用缓存且禁用 LLM")
    parser.add_argument("--start", help="回测开始日期，例如 2025-01-01")
    parser.add_argument("--end", help="回测结束日期，例如 2026-10-20")
    parser.add_argument("--max-shares", type=int, default=1100, help="回测最大计划股数")
    parser.add_argument("--capital", type=float, help="回测初始资金；默认按最大股数与首日收盘价计算")
    parser.add_argument("--initial-shares", type=int, default=0, help="回测起始持仓股数，默认 0（空仓开始）")
    parser.add_argument("--cooldown", type=int, default=0, help="风险卖出后的回测冷却交易日数")
    parser.add_argument("--walk-forward", action="store_true", help="滚动训练窗口校准观察区后再交易")
    parser.add_argument("--train-days", type=int, default=250, help="walk-forward 训练窗口交易日数")
    parser.add_argument("--rebalance-days", type=int, default=60, help="walk-forward 重新校准间隔")
    parser.add_argument("--warmup", type=int, default=260, help="回测指标预热 K 线数")
    parser.add_argument("--days", type=int, help="download 时请求的自然日数；默认读取 config.yaml")
    args = parser.parse_args()
    settings, repository = bootstrap()
    if args.command in ("web", "server"):
        import uvicorn
        from app.main import create_app

        import os

        host = (
            "0.0.0.0"
            if args.command == "server" or os.getenv("PORT")
            else os.getenv("WEB_HOST", "127.0.0.1")
        )
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run(create_app(settings, repository), host=host, port=port, workers=1)
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
        settings_db = settings.path("data/settings.db")
        if settings_db.exists():
            backup_database(settings_db, settings.path("backup"), retention_days=settings.config["storage"]["backup_retention_days"], prefix="settings")
        print(f"备份完成：{target}")
        return
    if args.command == "init-db":
        print("SQLite 已初始化")
        return
    if args.command == "backtest":
        from app.backtest.engine import (
            BacktestConfig,
            run_backtest,
            run_walk_forward,
            save_backtest,
        )

        config = BacktestConfig(
            code=normalize_code(args.code),
            start=args.start,
            end=args.end,
            max_shares=args.max_shares,
            initial_cash=args.capital,
            initial_shares=args.initial_shares,
            cooldown_days=args.cooldown,
            warmup_bars=args.warmup,
        )
        if args.walk_forward:
            result = run_walk_forward(
                settings,
                repository,
                config,
                train_days=args.train_days,
                rebalance_days=args.rebalance_days,
            )
            tag = "wf"
        else:
            result = run_backtest(settings, repository, config)
            tag = ""
        md_path, json_path = save_backtest(result, settings.root, tag=tag)
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        print(f"回测报告：{md_path}")
        print(f"回测明细：{json_path}")
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
    code = normalize_code(args.code)
    days = args.days or settings.config["market"]["history_days"]
    frame, warnings = MarketService(providers(), repository).update(code, days)
    adjusted, adj_warnings = MarketService(
        adjusted_providers(), repository
    ).update_adjusted(code, days)
    result = {
        "bars": len(frame),
        "adjusted_bars": len(adjusted),
        "latest": None if frame.empty else frame.iloc[-1]["date"],
        "warnings": warnings + adj_warnings,
        "minimum_met": len(frame) >= 250,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if frame.empty:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
