"""交易日确认后运行，无法确认日历时跳过，绝不把工作日等同交易日。"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import json
import logging
import os
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.data.bounded import fetch
from app.analysis.runner import AnalysisRunner
from app.data.market_provider import MarketService
from app.data.remote_market import providers
from app.database.backup import backup_database, clean_reports


class TradingCalendar:
    def __init__(self, cache: Path) -> None:
        self.cache = cache

    def previous_open_day(self, day: date) -> date | None:
        for offset in range(1, 31):
            candidate = day - timedelta(days=offset)
            opened = self.is_open(candidate)
            if opened is True:
                return candidate
            if opened is None:
                return None
        return None

    def is_open(self, day: date) -> bool | None:
        if day.weekday() >= 5:
            return False
        if self.cache.exists():
            try:
                payload = json.loads(self.cache.read_text(encoding="utf-8"))
                if payload["start"] <= day.isoformat() <= payload["end"]:
                    return day.isoformat() in payload["open_days"]
            except (ValueError, KeyError):
                logging.warning("交易日历缓存无效，尝试重新获取")
        if os.getenv("TUSHARE_TOKEN"):
            try:
                frame = fetch(
                    "tushare_trade_cal",
                    {
                        "exchange": "SSE",
                        "start_date": f"{day.year}0101",
                        "end_date": f"{day.year}1231",
                    },
                )
                if not frame.empty:
                    dates = frame.cal_date.astype(str).apply(
                        lambda x: f"{x[:4]}-{x[4:6]}-{x[6:8]}"
                    )
                    payload = {
                        "start": dates.min(),
                        "end": dates.max(),
                        "open_days": dates[frame.is_open.astype(int) == 1].tolist(),
                        "source": "Tushare SSE trade_cal",
                    }
                    self.cache.write_text(json.dumps(payload), encoding="utf-8")
                    if payload["start"] <= day.isoformat() <= payload["end"]:
                        return day.isoformat() in payload["open_days"]
            except Exception as exc:
                logging.warning("Tushare日历不可用：%s", type(exc).__name__)
        try:
            frame = fetch("tool_trade_date_hist_sina", {})
            dates = sorted(str(x)[:10] for x in frame.trade_date)
            if dates:
                payload = {
                    "start": dates[0],
                    "end": dates[-1],
                    "open_days": dates,
                    "source": "AKShare 新浪交易日历",
                }
                self.cache.write_text(json.dumps(payload), encoding="utf-8")
                if dates[0] <= day.isoformat() <= dates[-1]:
                    return day.isoformat() in dates
        except Exception as exc:
            logging.warning("备用日历不可用：%s", type(exc).__name__)
        return None


def daily_job(
    runner: AnalysisRunner, calendar: TradingCalendar, day: date | None = None
) -> bool:
    day = day or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    opened = calendar.is_open(day)
    if opened is not True:
        logging.info(
            "跳过定时分析 date=%s reason=%s",
            day,
            "非交易日" if opened is False else "交易日历无法确认",
        )
        return False
    if not runner.reserve():
        logging.info("已有分析任务，跳过重复触发")
        return False
    runner.run_reserved("603283.SH")
    return runner.last_error is None


def daily_retry_job(
    runner: AnalysisRunner, calendar: TradingCalendar, day: date | None = None
) -> bool:
    """Retry the close report once if the 15:05 run saw a stale daily bar."""
    day = day or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if calendar.is_open(day) is not True:
        return False
    latest = runner.analyzer.repository.reports(limit=1)
    if latest and latest[0].get("market", {}).get("date") == day.isoformat():
        logging.info("15:05 日报已使用当日行情，跳过重试")
        return False
    return daily_job(runner, calendar, day)


def intraday_snapshot_job(
    runner: AnalysisRunner,
    calendar: TradingCalendar,
    session: str,
    day: date | None = None,
) -> bool:
    """Send a lightweight price/trend snapshot at the three intraday checkpoints."""
    day = day or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if calendar.is_open(day) is not True:
        return False
    try:
        from app.data.realtime_quote import fetch_realtime_quote

        quote = fetch_realtime_quote("603283.SH")
    except Exception as exc:
        logging.warning("盘中快照行情获取失败：%s", type(exc).__name__)
        return False
    if quote.get("date") != day.isoformat():
        logging.warning("盘中快照报价日期不是今天，跳过")
        return False
    reports = runner.analyzer.repository.reports(limit=1)
    report = reports[0] if reports else {}
    result = runner.notifier.intraday(report, quote, session) if runner.notifier else False
    return result is True


def market_update_job(repository, calendar: TradingCalendar, day: date | None = None) -> bool:
    day = day or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    if calendar.is_open(day) is not True:
        return False
    frame, _ = MarketService(providers(), repository).update("603283.SH", 15)
    return not frame.empty


def maintenance_job(root: Path, storage: dict) -> str:
    result = backup_database(root / "data/stock_agent.db", root / "backup", retention_days=storage.get("backup_retention_days", 30))
    settings_db = root / "data/settings.db"
    if settings_db.exists():
        backup_database(settings_db, root / "backup", retention_days=storage.get("backup_retention_days", 30), prefix="settings")
    clean_reports(root / "reports", storage.get("report_retention_days", 365), storage.get("archive_old_reports", False))
    return str(result)


def build_scheduler(
    runner: AnalysisRunner, calendar: TradingCalendar, config: dict, monitor=None, repository=None, root: Path | None = None, storage: dict | None = None
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        daily_job,
        trigger=CronTrigger(
            hour=config["hour"], minute=config["minute"], timezone="Asia/Shanghai"
        ),
        args=[runner, calendar],
        id="daily_stock_analysis",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        daily_retry_job,
        trigger=CronTrigger(
            hour=config.get("retry_hour", 15),
            minute=config.get("retry_minute", 20),
            timezone="Asia/Shanghai",
        ),
        args=[runner, calendar],
        id="daily_stock_analysis_retry",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    intraday = config.get("intraday") or {}
    if intraday.get("enabled", True):
        for key, session, default in (
            ("morning_open", "上午开盘", "09:35"),
            ("morning_close", "上午收盘", "11:35"),
            ("afternoon_open", "下午开盘", "13:05"),
        ):
            value = str(intraday.get(key, default))
            try:
                hour, minute = (int(part) for part in value.split(":", 1))
            except (TypeError, ValueError):
                logging.warning("盘中快照时间配置无效：%s=%s", key, value)
                continue
            scheduler.add_job(
                intraday_snapshot_job,
                trigger=CronTrigger(
                    hour=hour, minute=minute, timezone="Asia/Shanghai"
                ),
                args=[runner, calendar, session],
                id=f"intraday_{key}",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=1800,
            )
    if repository is not None:
        scheduler.add_job(market_update_job, trigger=CronTrigger(hour=config.get("market_update_hour", 15), minute=config.get("market_update_minute", 10), timezone="Asia/Shanghai"), args=[repository, calendar], id="close_market_update", replace_existing=True, coalesce=True, max_instances=1)
    if monitor is not None and monitor.settings.config["monitor"].get("enabled", True):
        scheduler.add_job(monitor.poll, "interval", seconds=monitor.settings.config["monitor"]["interval_seconds"], id="realtime_monitor", replace_existing=True, coalesce=True, max_instances=1, next_run_time=datetime.now(ZoneInfo("Asia/Shanghai")))
    if root is not None:
        scheduler.add_job(maintenance_job, trigger=CronTrigger(hour=config.get("backup_hour", 2), minute=config.get("backup_minute", 0), timezone="Asia/Shanghai"), args=[root, storage or {}], id="database_backup", replace_existing=True, coalesce=True, max_instances=1)
    return scheduler
