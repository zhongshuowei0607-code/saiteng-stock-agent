"""交易日确认后运行，无法确认日历时跳过，绝不把工作日等同交易日。"""

from datetime import date, datetime
from zoneinfo import ZoneInfo
import json
import logging
import os
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.data.bounded import fetch
from app.analysis.runner import AnalysisRunner


class TradingCalendar:
    def __init__(self, cache: Path) -> None:
        self.cache = cache

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


def build_scheduler(
    runner: AnalysisRunner, calendar: TradingCalendar, config: dict
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
    return scheduler
