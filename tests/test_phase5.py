from fastapi.testclient import TestClient
from app.main import create_app
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository
from app.analysis.stock_analyzer import StockAnalyzer
from app.analysis.runner import AnalysisRunner
from test_phase2 import sample


def test_api_and_dashboard(tmp_path):
    import shutil

    settings = load_settings()
    shutil.copytree(settings.path("app/web"), tmp_path / "app/web")
    (tmp_path / "data").mkdir()
    shutil.copy(settings.path("data/portfolio.json"), tmp_path / "data/portfolio.json")
    portfolio_data = __import__("json").loads(
        (tmp_path / "data/portfolio.json").read_text(encoding="utf-8")
    )
    expected_average = sum(
        item["price"] * item["shares"] for item in portfolio_data["buys"]
    ) / sum(item["shares"] for item in portfolio_data["buys"])
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
        assert (
            client.get("/api/stock/603283/portfolio").json()["average_cost"]
            == expected_average
        )
        assert client.get("/api/stock/000001").status_code == 404
        assert client.get("/api/reports").status_code == 200
        assert (
            client.post(
                "/api/stock/603283/analyze", headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        app.state.runner.reserve()
        duplicate = client.post("/api/stock/603283/analyze")
        assert duplicate.status_code == 202
        assert duplicate.json()["status"] == "already_running"
        assert client.get("/reports/603283/invalid.html").status_code == 404


def test_analysis_runner_exposes_progress_state():
    class Analyzer:
        def analyze(self, code, progress=None):
            progress("llm", "等待 AI 生成今日总结")
            return {"date": "2026-09-09"}

    runner = AnalysisRunner(Analyzer())
    assert runner.reserve()
    assert runner.status()["stage"] == "queued"
    runner.run_reserved()
    status = runner.status()
    assert status["running"] is False
    assert status["stage"] == "complete"
    assert status["message"] == "分析完成，日报已更新"
