from app.notifications.bark import send_bark
from app.notifications.email import send_email
from app.notifications.service import NotificationService


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
