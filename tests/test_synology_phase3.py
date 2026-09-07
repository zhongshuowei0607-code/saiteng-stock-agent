import base64
import shutil

from fastapi.testclient import TestClient
from app.bootstrap import bootstrap
from app.main import create_app


def prepared(tmp_path):
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copytree("app/web", tmp_path / "app/web")
    shutil.copy("VERSION", tmp_path / "VERSION")
    return bootstrap(tmp_path)


def test_setup_encrypts_secrets_and_enables_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("WEB_AUTH_REQUIRED", "true")
    settings, repository = prepared(tmp_path)
    app = create_app(settings, repository)
    payload = {"tushare_token": "secret-token", "llm_provider": "disabled", "web_username": "owner", "web_password": "a-secure-password", "max_shares": 1000}
    with TestClient(app) as client:
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.get("/setup").status_code == 200
        assert client.post("/api/setup", json=payload).status_code == 200
        assert client.get("/").status_code == 401
        auth = base64.b64encode(b"owner:a-secure-password").decode()
        assert client.get("/", headers={"Authorization": "Basic " + auth}).status_code == 200
    database_bytes = (tmp_path / "data/stock_agent.db").read_bytes()
    assert b"secret-token" not in database_bytes
    assert app.state.secure_settings.masked("TUSHARE_TOKEN") == "••••••••"


def test_environment_has_priority(tmp_path, monkeypatch):
    settings, repository = prepared(tmp_path)
    store = create_app(settings, repository).state.secure_settings
    store.set("TUSHARE_TOKEN", "database")
    monkeypatch.setenv("TUSHARE_TOKEN", "environment")
    assert store.get("TUSHARE_TOKEN") == "environment"
