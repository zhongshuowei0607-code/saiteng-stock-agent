from app.notifications.bark import send_bark
from app.notifications.email import send_email
from app.notifications.service import NotificationService, actionable_signals
from datetime import datetime
from zoneinfo import ZoneInfo


def test_bark_mock(monkeypatch):
    monkeypatch.setenv("BARK_ENABLED", "true")
    monkeypatch.setenv("BARK_DEVICE_KEY", "device")
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    monkeypatch.setattr("app.notifications.bark.httpx.post", lambda *a, **k: calls.append((a, k)) or Response())
    assert send_bark("标题", "内容", "WARNING")
    assert calls[0][1]["timeout"] == 10


def test_bark_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("BARK_ENABLED", "true")
    monkeypatch.setenv("BARK_DEVICE_KEY", "device")
    monkeypatch.setattr("app.notifications.bark.time.sleep", lambda _: None)
    monkeypatch.setattr("app.notifications.bark.httpx.post", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert send_bark("标题", "内容") is False


def test_email_mock(monkeypatch):
    for key, value in {"EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.example", "SMTP_USER": "user", "SMTP_PASSWORD": "authorization-code", "SMTP_FROM": "from@example", "SMTP_TO": "to@example"}.items():
        monkeypatch.setenv(key, value)
    sent = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, user, password):
            assert password == "authorization-code"
        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("app.notifications.email.smtplib.SMTP_SSL", SMTP)
    assert send_email("测试", "正文")
    assert len(sent) == 1


def test_email_uses_certifi_ca_bundle(monkeypatch):
    for key, value in {"EMAIL_ENABLED": "true", "SMTP_HOST": "smtp.example", "SMTP_USER": "user", "SMTP_PASSWORD": "authorization-code", "SMTP_FROM": "from@example", "SMTP_TO": "to@example"}.items():
        monkeypatch.setenv(key, value)
    contexts = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            contexts.append(kwargs["context"])
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, user, password):
            pass
        def send_message(self, message):
            pass

    monkeypatch.setattr("app.notifications.email.smtplib.SMTP_SSL", SMTP)
    assert send_email("测试", "正文")
    assert contexts


def test_qq_email_uses_full_sender_as_login(monkeypatch):
    values = {
        "EMAIL_ENABLED": "true",
        "SMTP_HOST": "smtp.qq.com",
        "SMTP_USER": "nickname",
        "SMTP_PASSWORD": "authorization-code",
        "SMTP_FROM": "owner@qq.com",
        "SMTP_TO": "to@example.com",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    logins = []

    class SMTP:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, user, password):
            logins.append(user)
        def send_message(self, message):
            pass

    monkeypatch.setattr("app.notifications.email.smtplib.SMTP_SSL", SMTP)
    assert send_email("测试", "正文")
    assert logins == ["owner@qq.com"]


def test_daily_email_is_sent_once_and_failure_can_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    service = NotificationService(tmp_path)
    monkeypatch.setattr(service, "bark", lambda *args: False)
    sent = []
    monkeypatch.setattr(
        service, "email", lambda *args: sent.append(args) or len(sent) > 1
    )
    report = {
        "date": "2026-09-09",
        "risk": {"score": 63},
        "ai": {"summary": "测试摘要"},
    }

    assert service.daily(report)["email"] is False
    assert service.daily(report)["email"] is True
    assert service.daily(report)["email"] == "already_sent"
    assert len(sent) == 2


def test_actionable_signals_cover_buy_sell_and_risk():
    buy = {
        "watch_zone": {"state": "第一加仓观察区", "confirmed": True},
        "stabilization": {"score": 8},
        "risk": {"score": 40},
        "market": {"close": 42},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500},
        "levels": {"support": [], "resistance": []},
    }
    assert {item["category"] for item in actionable_signals(buy)} == {"buy"}
    sell = {
        "watch_zone": {"state": "反弹减仓观察区", "confirmed": False},
        "risk": {"score": 50},
        "market": {"close": 49},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500},
        "levels": {"support": [], "resistance": []},
    }
    assert {item["category"] for item in actionable_signals(sell)} == {"sell"}
    rebound = {
        "watch_zone": {"state": "反弹观察区", "confirmed": False},
        "risk": {"score": 50},
        "market": {"close": 49},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500},
        "levels": {"support": [], "resistance": []},
    }
    rebound_signal = actionable_signals(rebound)[0]
    assert rebound_signal["category"] == "sell"
    assert rebound_signal["shares"] == 100
    assert rebound_signal["shares_after"] == 400
    risk = {
        "watch_zone": {"state": "高风险区", "confirmed": False},
        "risk": {"score": 70},
        "market": {"close": 40},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500},
        "levels": {"support": [], "resistance": []},
    }
    assert {item["category"] for item in actionable_signals(risk)} == {"risk"}


def test_action_alert_sends_immediately_and_deduplicates(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_ENABLED", "true")
    service = NotificationService(tmp_path)
    sent = []
    monkeypatch.setattr(
        service,
        "email",
        lambda subject, body, attachment=None: sent.append(
            (subject, body, attachment)
        )
        or True,
    )
    report = {
        "date": "2026-09-21",
        "market": {"date": "2026-09-21", "close": 47.36, "is_realtime": True, "quote_time": "2026-09-21T10:00:00+08:00"},
        "technical_as_of": "2026-09-18",
        "baseline_current": True,
        "trading_session_open": True,
        "stale_data": False,
        "watch_zone": {"state": "反弹减仓观察区", "confirmed": False},
        "risk": {"score": 50},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500},
        "levels": {"support": [], "resistance": []},
        "ai": {"summary": "测试摘要", "conclusion": "测试结论"},
    }
    now = datetime(2026, 9, 21, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert service.action_alert(report, now=now)["email"]["sell"] is True
    assert service.action_alert(report, now=now)["email"]["sell"] == "already_sent"
    assert len(sent) == 1
    assert "减仓条件核对 200股" in sent[0][0]
    assert "参考股数：200 股" in sent[0][1]
    assert "触发后参考持仓：300 股" in sent[0][1]
    assert "不构成投资建议" in sent[0][1]


def test_analysis_runner_sends_action_alert_before_daily_notification():
    from app.analysis.runner import AnalysisRunner

    calls = []

    class Analyzer:
        def analyze(self, code, progress=None):
            return {"date": "2026-09-20", "watch_zone": {"state": "第一加仓观察区"}}

    class Notifier:
        def action_alert(self, report):
            calls.append("action")

        def daily(self, report):
            calls.append("daily")

    runner = AnalysisRunner(Analyzer(), Notifier())
    assert runner.reserve()
    runner.run_reserved()
    assert calls == ["action", "daily"]
