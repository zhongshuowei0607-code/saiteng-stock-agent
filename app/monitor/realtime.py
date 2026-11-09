from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging
from copy import deepcopy
from threading import Lock

from app.data.realtime_quote import fetch_realtime_quote
from app.analysis.action_plan import build_action_guide, quote_is_fresh
from app.analysis.risk_analyzer import risk_score
from app.portfolio.portfolio_service import load_position, watch_state

LOGGER = logging.getLogger("monitor")


def in_trading_session(moment: datetime) -> bool:
    local = moment.astimezone(ZoneInfo("Asia/Shanghai"))
    value = local.time().replace(tzinfo=None)
    return time(9, 30) <= value <= time(11, 30) or time(13, 0) <= value <= time(15, 0)


class RealtimeMonitor:
    def __init__(self, settings, repository, analyzer, calendar, trigger_engine) -> None:
        self.settings, self.repository, self.analyzer = settings, repository, analyzer
        self.calendar, self.trigger_engine = calendar, trigger_engine
        self.running = False
        self.last_successful_poll = None
        self.last_market_update = None
        self.stale_data = True
        self.failures = 0
        self.next_allowed = None
        self.latest_report = None
        self.last_error = None
        self.message = "等待交易时段"
        self.lock = Lock()

    def snapshot(self) -> dict | None:
        return deepcopy(self.latest_report)

    def poll(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        if self.next_allowed and now < self.next_allowed:
            return False
        if not self.settings.config.get("monitor", {}).get("enabled", True):
            self.message = "盘中监测未启用"
            return False
        if not in_trading_session(now) or self.calendar.is_open(now.date()) is not True:
            self.message = "休市或交易日历未确认，等待交易时段"
            return False
        if not self.lock.acquire(blocking=False):
            return False
        self.running = True
        try:
            previous = self.repository.reports()
            expected = self.calendar.previous_open_day(now.date())
            baseline_report = next(
                (
                    item for item in previous
                    if expected is not None
                    and item.get("market", {}).get("date") == expected.isoformat()
                ),
                previous[0] if previous else None,
            )
            if baseline_report is None:
                raise ValueError("尚无日线分析基准，请先更新并生成日报")
            report = deepcopy(baseline_report)
            baseline = report.get("market", {}).get("date")
            report["baseline_current"] = expected is not None and baseline == expected.isoformat()
            quote = fetch_realtime_quote("603283.SH")
            report["technical_as_of"] = baseline
            report["market"] = {**report.get("market", {}), **quote}
            report["stale_data"] = False
            report["monitor_interval_seconds"] = self.settings.config["monitor"]["interval_seconds"]
            self.stale_data = not quote_is_fresh(report, now)
            report["stale_data"] = self.stale_data
            self.last_market_update = quote["quote_time"]
            if self.stale_data:
                raise ValueError("行情源返回的报价已过期，暂停操作提醒")
            report["trading_session_open"] = True
            report["risk_config"] = self.settings.config["risk"]
            report["confirmation_score"] = self.settings.strategy["confirmation_score"]
            report["action_plan"] = self.settings.strategy.get("action_plan", {})
            report["position_zones"] = self.settings.strategy["zones"]
            report["portfolio"] = load_position(self.settings.path("data/portfolio.json")).valuation(quote["close"])
            # An intraday quote cannot confirm a daily close/volume breakout.
            report["breakout_confirmed"] = False
            report["watch_zone"] = watch_state(quote["close"], report.get("stabilization", {}), self.settings.strategy,
                event_stop=any(e.get("stop_adding_observation") is True for e in report.get("ai", {}).get("events", [])))
            report["risk"] = risk_score(report)
            report["decision"] = build_action_guide(report, now)
            # An intraday quote must never replace the saved daily report or AI text.
            self.latest_report = report
            self.trigger_engine.evaluate(
                report, self.settings.config["risk"], now
            )
            self.last_successful_poll = now.isoformat()
            self.failures = 0
            self.next_allowed = None
            self.last_error = None
            self.message = "实时报价已更新" if report["baseline_current"] else "报价已更新；请先补齐最近交易日日报，操作邮件已暂停"
            return True
        except Exception as exc:
            self.failures += 1
            self.stale_data = True
            self.last_error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            self.message = "行情监测异常，操作提醒暂停：" + self.last_error
            delays = (3, 10, 30, 60, 300)
            self.next_allowed = now + timedelta(seconds=delays[min(self.failures - 1, len(delays) - 1)])
            LOGGER.warning("实时轮询失败，进入退避：%s", type(exc).__name__)
            return False
        finally:
            self.running = False
            self.lock.release()

    def status(self) -> dict:
        fresh = self.latest_report is not None and quote_is_fresh(self.latest_report)
        return {"running": self.running, "last_successful_poll": self.last_successful_poll, "last_market_update": self.last_market_update, "stale_data": self.stale_data or not fresh, "failures": self.failures, "message": self.message, "error": self.last_error}
