from pathlib import Path
import shutil

from fastapi.testclient import TestClient

from app.main import create_app
from app.bootstrap import bootstrap


def test_dashboard_contains_required_features():
    page = Path("app/web/templates/dashboard.html").read_text()
    for text in ("Stock Agent v", "当前价", "持仓", "风险 / 企稳", "RSI", "今日触发记录", "历史日报", "系统设置", "AI 分析状态"):
        assert text in page
    script = Path("app/web/static/dashboard.js").read_text()
    assert "RSI14" in script and "/api/health" in script
    assert "renderAnalysis" in script and "elapsed_seconds" in script


def test_no_heavy_dependencies():
    requirements = Path("requirements.txt").read_text().lower()
    for package in ("talib", "selenium", "chromium", "redis", "celery", "postgres"):
        assert package not in requirements


def test_settings_page_supports_legacy_portfolio(tmp_path):
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copytree("app/web", tmp_path / "app/web")
    shutil.copy("VERSION", tmp_path / "VERSION")
    settings, repository = bootstrap(tmp_path)
    settings.path("data/portfolio.json").write_text(
        '{"code":"603283.SH","max_shares":1000,"buys":[]}',
        encoding="utf-8",
    )
    with TestClient(create_app(settings, repository)) as client:
        response = client.get("/settings")
    assert response.status_code == 200
    assert "买入记录" in response.text
    assert "卖出记录（可选）" in response.text
    assert "add-buy" in response.text
    assert 'step="0.001"' in response.text
    assert 'class="trade-shares" type="number" min="1" step="1"' in response.text


def test_setup_saves_editable_portfolio_and_refreshes_report(tmp_path):
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copytree("app/web", tmp_path / "app/web")
    shutil.copy("VERSION", tmp_path / "VERSION")
    settings, repository = bootstrap(tmp_path)
    with TestClient(create_app(settings, repository)) as client:
        response = client.post(
            "/api/setup",
            json={
                "llm_provider": "disabled",
                "web_username": "owner",
                "web_password": "a-secure-password",
                "max_shares": 1000,
                "account_equity": 100000,
                "cash": 50000,
                "available_shares": 400,
                "risk_per_trade_pct": 1.0,
                "atr_stop_multiplier": 2.0,
                "buys": [{"price": 49.625, "shares": 500}],
                "sells": [],
            },
        )
        assert response.status_code == 200
        assert response.json()["portfolio"]["shares"] == 500
        assert response.json()["portfolio"]["average_cost"] == 49.625
        assert response.json()["portfolio"]["account_equity"] == 100000
        assert response.json()["portfolio"]["available_shares"] == 400
        saved = settings.path("data/portfolio.json").read_text(encoding="utf-8")
        assert '"price": 49.625' in saved and '"shares": 500' in saved
        assert '"account_equity": 100000.0' in saved and '"available_shares": 400' in saved
        latest = client.get("/api/stock/603283").json()
        assert latest["portfolio"]["average_cost"] == 49.625
