from fastapi.testclient import TestClient
from app.main import create_app
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository
from app.analysis.stock_analyzer import StockAnalyzer
from test_phase2 import sample


def test_api_and_dashboard(tmp_path):
    import shutil

    settings = load_settings()
    shutil.copytree(settings.path("app/web"), tmp_path / "app/web")
    (tmp_path / "data").mkdir()
    shutil.copy(settings.path("data/portfolio.json"), tmp_path / "data/portfolio.json")
    settings.root = tmp_path
    repo = Repository(create_db(tmp_path / "db"))
    # 测试写出的报告只进入临时目录，模板沿用真实资源。
    repo.save_bars("603283.SH", sample())
    report = StockAnalyzer(settings, repo).analyze(refresh=False, use_llm=False)
    app = create_app(settings, repo)
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200 and "赛腾股份" in response.text
        for path in ("", "/history", "/technical", "/portfolio", "/report/latest"):
            assert client.get("/api/stock/603283" + path).status_code == 200
        assert client.get("/api/stock/603283/portfolio").json()["average_cost"] == 49
        assert client.get("/api/stock/000001").status_code == 404
        assert client.get("/api/reports").status_code == 200
        assert (
            client.post(
                "/api/stock/603283/analyze", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        app.state.runner.reserve()
        assert client.post("/api/stock/603283/analyze").status_code == 409
        assert client.get("/reports/603283/invalid.html").status_code == 404
