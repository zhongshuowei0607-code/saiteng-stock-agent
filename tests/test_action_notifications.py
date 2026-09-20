from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.monitor.triggers import TriggerEngine
from app.notifications.service import NotificationService


NOW = datetime(2026, 9, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
RISK_CONFIG = {"warning_threshold": 65, "critical_threshold": 85}


def live_report(now=NOW):
    return {
        "date": now.date().isoformat(),
        "stock": {"code": "603283.SH", "name": "赛腾股份"},
        "market": {"date": now.date().isoformat(), "close": 48.0,
                   "is_realtime": True, "quote_time": now.isoformat()},
        "technical_as_of": "2026-09-18", "baseline_current": True,
        "trading_session_open": True, "stale_data": False,
        "watch_zone": {"state": "反弹减仓观察区"},
        "risk": {"score": 40}, "stabilization": {"score": 8},
        "portfolio": {"shares": 500, "max_shares": 1500},
        "levels": {"support": [], "resistance": []},
        "ai": {"summary": "历史日报分析"},
    }


def test_email_has_time_checklist_and_invalidation(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    assert service.action_alert(live_report(), now=NOW)["email"] == {"sell": True}
    subject, body, _ = sent[0]
    assert "10:00" in subject
    for text in ("触发原因：", "处理时间：", "操作前逐项确认：", "T+1", "失效条件：", "参考股数：200 股", "2026-09-21T10:00:00+08:00", "2026-09-18，仅作背景参考"):
        assert text in body
    assert service.status()["action"]["status"] == "sent"


def test_failed_email_can_retry_after_service_restart(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    monkeypatch.setattr(service, "email", lambda *args: False)
    assert service.action_alert(live_report(), now=NOW)["email"] == {"sell": False}
    restarted = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(restarted, "email", lambda *args: sent.append(args) or True)
    assert restarted.status()["action"]["status"] == "failed"
    assert restarted.action_alert(live_report(), now=NOW)["email"] == {"sell": True}
    again = NotificationService(tmp_path)
    monkeypatch.setattr(again, "email", lambda *args: sent.append(args) or True)
    assert again.action_alert(live_report(), now=NOW)["email"] == {"sell": "already_sent"}
    assert len(sent) == 1
    assert [item["status"] for item in again.status()["recent"]] == ["sent", "failed"]


def test_new_signal_and_actual_position_change_not_swallowed(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    report = live_report()
    service.action_alert(report, now=NOW)
    report["watch_zone"]["state"] = "反弹观察区"
    assert service.action_alert(report, now=NOW)["email"] == {"sell": True}
    report["portfolio"]["shares"] = 1000
    assert service.action_alert(report, now=NOW)["email"] == {"sell": True}
    # Price movement within the same condition does not send another email.
    report["market"]["close"] = 48.01
    assert service.action_alert(report, now=NOW)["email"] == {"sell": "already_sent"}
    assert len(sent) == 3


def test_stale_saved_decision_cannot_send_action_email(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    report = live_report()
    report["decision"] = {"eligible_for_alert": True, "actions": [{"category": "buy"}]}
    assert service.action_alert(report, now=NOW + timedelta(minutes=11))["email"] == "blocked"
    assert not sent
    assert service.status()["action"]["status"] == "blocked"
    report["market"].pop("quote_time")
    assert service.action_alert(report, now=NOW)["email"] == "blocked"
    assert not sent


def test_lunch_and_closed_calendar_block_action_alerts(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    lunch = NOW.replace(hour=12)
    assert service.action_alert(live_report(lunch), now=lunch)["email"] == "blocked"
    report = live_report()
    report["trading_session_open"] = False
    assert service.action_alert(report, now=NOW)["email"] == "blocked"
    assert sent == []


def test_risk_suppresses_buy_and_critical_escalation_sends_again(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    report = live_report()
    report["watch_zone"]["state"] = "第一加仓观察区"
    report["risk"]["score"] = 70
    assert service.action_alert(report, now=NOW)["email"] == {"risk": True}
    assert "买入条件核对" not in sent[0][1]
    report["risk"]["score"] = 86
    assert service.action_alert(report, now=NOW)["email"] == {"risk": True}
    assert len(sent) == 2


def test_daily_deduplicates_market_date_even_when_report_regenerated(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(service, "email", lambda *args: sent.append(args) or True)
    monkeypatch.setattr(service, "bark", lambda *args: False)
    report = live_report()
    report["market"]["date"] = "2026-09-18"
    report["date"] = "2026-09-19"
    assert service.daily(report)["email"] is True
    report["date"] = "2026-09-20"
    assert service.daily(report)["email"] == "already_sent"
    assert len(sent) == 1
    assert "时间安排：" in sent[0][1]


def test_raised_mail_error_is_recorded_and_remains_retryable(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)

    def fail(*args):
        raise OSError("SMTP connection unavailable")

    monkeypatch.setattr(service, "email", fail)
    assert service.action_alert(live_report(), now=NOW)["email"] == {"sell": False}
    assert service.status()["action"]["status"] == "failed"
    monkeypatch.setattr(service, "email", lambda *args: True)
    assert service.action_alert(live_report(), now=NOW)["email"] == {"sell": True}


class MemoryRepository:
    def __init__(self):
        self.states, self.events = {}, []

    def trigger_state(self, signal):
        return deepcopy(self.states.get(signal))

    def save_trigger_state(self, signal, state, last_triggered, updated_at):
        self.states[signal] = {"state": state, "last_triggered": last_triggered, "updated_at": updated_at}

    def add_trigger_event(self, *args):
        self.events.append(args)


def test_triggered_bark_does_not_prevent_email_retry(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    calls, barks = [], []
    monkeypatch.setattr(service, "email", lambda *args: calls.append(args) or len(calls) > 1)
    monkeypatch.setattr(service, "bark", lambda *args: barks.append(args) or True)
    engine = TriggerEngine(MemoryRepository(), service)
    assert len(engine.evaluate(live_report(), RISK_CONFIG, now=NOW)) == 1
    assert engine.evaluate(live_report(), RISK_CONFIG, now=NOW) == []
    assert len(calls) == 2 and len(barks) == 1
    assert service.status()["action"]["status"] == "sent"


def test_signal_returning_in_cooldown_emits_after_cooldown(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    barks = []
    monkeypatch.setattr(service, "email", lambda *args: True)
    monkeypatch.setattr(service, "bark", lambda *args: barks.append(args) or True)
    repository = MemoryRepository()
    engine = TriggerEngine(repository, service, cooldown_minutes=30)
    assert len(engine.evaluate(live_report(), RISK_CONFIG, now=NOW)) == 1
    inactive = live_report(NOW + timedelta(minutes=1))
    inactive["watch_zone"]["state"] = "持仓观察"
    assert engine.evaluate(inactive, RISK_CONFIG, now=NOW + timedelta(minutes=1)) == []
    pending_time = NOW + timedelta(minutes=2)
    assert engine.evaluate(live_report(pending_time), RISK_CONFIG, now=pending_time) == []
    assert repository.trigger_state("SELL_WATCH_LEVEL_2")["state"] == "PENDING"
    eligible_time = NOW + timedelta(minutes=31)
    assert len(engine.evaluate(live_report(eligible_time), RISK_CONFIG, now=eligible_time)) == 1
    assert len(barks) == 2


def test_stale_quotes_do_not_consume_trigger_state(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    calls = []
    monkeypatch.setattr(service, "email", lambda *args: calls.append(args) or True)
    monkeypatch.setattr(service, "bark", lambda *args: calls.append(args) or True)
    repository = MemoryRepository()
    engine = TriggerEngine(repository, service)
    assert engine.evaluate(live_report(), RISK_CONFIG, now=NOW + timedelta(hours=1)) == []
    assert repository.states == {} and calls == []


def test_same_active_signal_can_notify_on_next_trading_day(tmp_path, monkeypatch):
    service = NotificationService(tmp_path)
    monkeypatch.setattr(service, "email", lambda *args: True)
    monkeypatch.setattr(service, "bark", lambda *args: True)
    engine = TriggerEngine(MemoryRepository(), service)
    assert len(engine.evaluate(live_report(), RISK_CONFIG, now=NOW)) == 1
    tomorrow = NOW + timedelta(days=1)
    assert len(engine.evaluate(live_report(tomorrow), RISK_CONFIG, now=tomorrow)) == 1
