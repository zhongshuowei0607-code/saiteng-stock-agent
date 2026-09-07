from datetime import datetime
from zoneinfo import ZoneInfo

from app.bootstrap import bootstrap
from app.monitor.realtime import in_trading_session
from app.monitor.triggers import TriggerEngine


class Notifier:
    def __init__(self):
        self.sent = []
    def bark(self, title, message, level):
        self.sent.append((title, message, level))
        return True


def test_trading_sessions_and_timezone():
    tz = ZoneInfo("Asia/Shanghai")
    assert in_trading_session(datetime(2026, 9, 7, 9, 30, tzinfo=tz))
    assert in_trading_session(datetime(2026, 9, 7, 14, 59, tzinfo=tz))
    assert not in_trading_session(datetime(2026, 9, 7, 12, 0, tzinfo=tz))
    assert not in_trading_session(datetime(2026, 9, 7, 15, 1, tzinfo=tz))


def test_trigger_state_prevents_repeated_notifications(tmp_path):
    import shutil
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copy("VERSION", tmp_path / "VERSION")
    _, repository = bootstrap(tmp_path)
    notifier = Notifier()
    engine = TriggerEngine(repository, notifier, 30)
    report = {"watch_zone": {"state": "第一加仓观察区"}, "risk": {"score": 70}, "market": {"close": 42.5}, "levels": {"support": [], "resistance": []}, "stabilization": {"level": "LOW"}}
    now = datetime(2026, 9, 7, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    first = engine.evaluate(report, {"warning_threshold": 65, "critical_threshold": 85}, now)
    second = engine.evaluate(report, {"warning_threshold": 65, "critical_threshold": 85}, now)
    assert {item["signal"] for item in first} == {"BUY_WATCH_LEVEL_1", "RISK_WARNING"}
    assert second == [] and len(notifier.sent) == 2
    report["watch_zone"]["state"] = "持仓观察"
    report["risk"]["score"] = 30
    engine.evaluate(report, {"warning_threshold": 65, "critical_threshold": 85}, now)
    assert repository.trigger_state("BUY_WATCH_LEVEL_1")["state"] == "RESET"
