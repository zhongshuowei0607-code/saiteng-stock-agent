from app.analysis.event_analyzer import classify
from app.data.fundamental_provider import compare_financials
from app.data.industry_provider import comparison
from app.data.announcement_provider import AnnouncementProvider
from app.llm.base import explain
from test_phase2 import sample
from test_phase3 import valid_ai
import json


def test_events_dedupe():
    row = dict(
        title="股东减持公告",
        url="https://www.cninfo.com.cn/x",
        date="2026-09-01",
        raw_text="",
    )
    result = classify([row, row])
    assert len(result) == 1 and result[0]["risk_flag"]
    assert "仅标题" in result[0]["analysis_scope"]


def test_announcement_falls_back_to_eastmoney(monkeypatch):
    import pandas as pd

    def fake_fetch(name, *args, **kwargs):
        assert name == "stock_individual_notice_report"
        return pd.DataFrame(
            [
                {
                    "公告标题": "关于回购公司股份的公告",
                    "公告日期": "2026-09-18",
                    "网址": "https://data.eastmoney.com/notices/detail/603283/1.html",
                }
            ]
        )

    monkeypatch.setattr("app.data.announcement_provider.fetch", fake_fetch)
    rows = AnnouncementProvider().fetch("603283.SH")
    assert len(rows) == 1
    assert rows[0]["source"] == "东方财富公告"
    assert rows[0]["text_status"] == "仅标题（东方财富）"


def test_announcement_full_text_marks_control_change(monkeypatch):
    import pandas as pd

    def fake_fetch(name, *args, **kwargs):
        return pd.DataFrame(
            [
                {
                    "公告标题": "关于股东部分股份质押及解除质押的公告",
                    "公告日期": "2026-10-16",
                    "网址": "https://data.eastmoney.com/notices/detail/603283/AN202610161830610178.html",
                }
            ]
        )

    monkeypatch.setattr("app.data.announcement_provider.fetch", fake_fetch)
    monkeypatch.setattr(
        "app.data.announcement_provider.extract_eastmoney_text",
        lambda url: "孙丰先生、曾慧女士因离婚股权分割，公司控制权可能会发生变更。",
    )
    rows = AnnouncementProvider().fetch("603283.SH")
    assert rows[0]["raw_text"]
    assert "控制权变更" in rows[0]["categories"]
    assert rows[0]["risk_flag"]
    assert "全文" in rows[0]["text_status"]


def test_financial_same_period():
    rows = [
        dict(
            end_date="2026-06-30",
            net_profit=150,
            operating_cashflow=80,
            inventory=200,
            receivables=180,
        ),
        dict(end_date="2026-03-31", net_profit=2),
        dict(
            end_date="2025-06-30",
            net_profit=100,
            operating_cashflow=100,
            inventory=100,
            receivables=100,
        ),
    ]
    result = compare_financials(rows)
    assert result["yoy_changes"]["net_profit"] == 50
    assert len(result["warnings"]) == 3


def test_industry_alignment():
    frame = sample()
    frame["pct_change"] = 2
    other = sample()
    other["pct_change"] = 0
    result = comparison(
        {"603283.SH": frame, "688097.SH": other},
        {"603283.SH": "赛腾", "688097.SH": "博众"},
        "603283.SH",
    )
    assert result["relative"] == "个股强于行业"
    result = comparison(
        {"603283.SH": frame, "688097.SH": other.iloc[:-1]},
        {"603283.SH": "赛腾", "688097.SH": "博众"},
        "603283.SH",
    )
    assert result["relative"] == "数据不足，无法判断。"


def test_hallucinated_event():
    data = valid_ai()
    data["events"] = [
        dict(
            id="invented",
            category="回购",
            importance=90,
            sentiment="positive",
            summary="x",
            impact="x",
            horizon="x",
            affects_thesis=True,
            stop_adding_observation=False,
        )
    ]

    class Mock:
        def complete(self, facts):
            return json.dumps(data)

    assert explain(Mock(), {"market": {"close": 43}})["status"] == "unavailable"
