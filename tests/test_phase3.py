import json
from app.llm.base import explain, AIReport
from app.llm.factory import make_provider
from app.llm.prompts import SYSTEM
from app.analysis.daily_report import render_reports
from app.analysis.stock_analyzer import StockAnalyzer
from app.analysis.risk_analyzer import risk_score
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository
from test_phase2 import sample


def valid_ai():
    return dict(
        summary="仅观察",
        trend="观察",
        risk="观察",
        portfolio_analysis="观察",
        watch_zone="观察",
        stabilization="观察",
        bullish_factors=[],
        bearish_factors=[],
        next_day_focus=[],
        conclusion="观察",
        events=[],
    )


def test_llm_validation():
    class Mock:
        def __init__(self, data):
            self.data = data

        def complete(self, facts):
            return self.data

    facts = {"market": {"close": 49}}
    assert explain(Mock(json.dumps(valid_ai())), facts)["status"] == "generated"
    assert explain(Mock("not json"), facts)["status"] == "unavailable"
    data = valid_ai()
    data["summary"] = "立即买入"
    assert explain(Mock(json.dumps(data)), facts)["status"] == "unavailable"
    assert explain(None, facts)["status"] == "unavailable"


def test_prompt_prefers_arabic_numbers():
    assert "优先使用阿拉伯数字" in SYSTEM


def test_llm_accepts_fenced_json():
    class Mock:
        def complete(self, facts):
            return "```json\n" + json.dumps(valid_ai(), ensure_ascii=False) + "\n```"

    assert explain(Mock(), {"market": {"close": 49}})["status"] == "generated"


def test_title_only_event_keeps_bounded_ai_impact():
    data = valid_ai()
    data["events"] = [
        {
            "id": "event-1",
            "category": "股东减持",
            "importance": 70,
            "sentiment": "negative",
            "summary": "公司披露股东减持相关公告。",
            "impact": "可能影响短期市场情绪。",
            "horizon": "短期",
            "affects_thesis": False,
            "stop_adding_observation": False,
        }
    ]

    class Mock:
        def complete(self, facts):
            return json.dumps(data, ensure_ascii=False)

    facts = {
        "market": {"close": 49},
        "news": [],
        "announcements": [
            {
                "id": "event-1",
                "title": "股东减持公告",
                "raw_text": "",
            }
        ],
    }
    result = explain(Mock(), facts)
    event = result["events"][0]
    assert result["status"] == "generated"
    assert event["affects_thesis"] is None
    assert event["stop_adding_observation"] is None
    assert event["impact"].startswith("仅据标题：")


def test_risk_missing():
    assert risk_score({})["score"] is None


def test_pipeline(tmp_path):
    settings = load_settings()
    settings.root = tmp_path
    (tmp_path / "data").mkdir()
    (tmp_path / "data/portfolio.json").write_text(
        '{"code":"603283.SH","max_shares":1000,"buys":[{"price":50,"shares":200},{"price":48,"shares":200}]}'
    )
    repo = Repository(create_db(tmp_path / "test.db"))
    repo.save_bars("603283.SH", sample())
    report = StockAnalyzer(settings, repo).analyze(refresh=False, use_llm=False)
    assert report["portfolio"]["average_cost"] == 49
    assert 0 <= report["risk"]["score"] <= 100
    assert len(repo.reports()) == 1
    assert (tmp_path / "reports/603283" / f"{report['date']}.html").exists()
    report["ai"]["summary"] = "<script>alert(1)</script>"
    _, page = render_reports(report, tmp_path / "reports")
    assert "<script>" not in page.read_text()
