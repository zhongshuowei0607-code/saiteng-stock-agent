from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import logging

from app.data.market_provider import MarketService
from app.data.remote_market import providers

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

    def poll(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        if self.next_allowed and now < self.next_allowed:
            return False
        if not in_trading_session(now) or self.calendar.is_open(now.date()) is not True:
            return False
        self.running = True
        try:
            frame, warnings = MarketService(providers(), self.repository).update("603283.SH", 15)
            latest = None if frame.empty else str(frame.iloc[-1]["date"])
            self.stale_data = bool(warnings) or latest != now.date().isoformat()
            self.last_market_update = latest
            report = self.analyzer.analyze(refresh=False, use_llm=False)
            report["stale_data"] = self.stale_data
            self.trigger_engine.evaluate(report, self.settings.config["risk"], now)
            self.last_successful_poll = now.isoformat()
            self.failures = 0
            self.next_allowed = None
            return True
        except Exception as exc:
            self.failures += 1
            delays = (3, 10, 30, 60, 300)
            self.next_allowed = now + timedelta(seconds=delays[min(self.failures - 1, len(delays) - 1)])
            LOGGER.warning("实时轮询失败，进入退避：%s", type(exc).__name__)
            return False
        finally:
            self.running = False

    def status(self) -> dict:
        return {"running": self.running, "last_successful_poll": self.last_successful_poll, "last_market_update": self.last_market_update, "stale_data": self.stale_data, "failures": self.failures}
