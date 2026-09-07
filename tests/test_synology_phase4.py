from app.notifications.bark import send_bark
from app.notifications.email import send_email


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
