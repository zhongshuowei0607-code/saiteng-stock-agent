from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.analysis.daily_report import render_reports


ROOT = Path(__file__).resolve().parents[1]


def report_fixture():
    return {
        "stock": {"code": "603283.SH", "name": "赛腾股份"},
        "date": "2026-09-21",
        "market": {"date": "2026-09-18", "close": 43.2, "pct_change": -0.7},
        "portfolio": {"shares": 500, "max_shares": 1000, "remaining_shares": 500,
                      "average_cost": 45.0, "position_ratio": 0.5, "pnl": -900.0, "pnl_pct": -4.0},
        "risk": {"score": 40}, "stabilization": {"score": 6},
        "watch_zone": {"state": "第一加仓观察区"},
        "levels": {"support": [], "resistance": []},
        "technical": [], "news": [], "announcements": [], "warnings": [],
        "industry": {"relative": "待更新"},
        "ai": {"status": "unavailable", "mode": "rules", "reason": "模型请求超时，可重新生成。",
               "summary": "已有行情与持仓可用于规则解读。", "trend": "短线偏弱",
               "risk": "中等风险", "portfolio_analysis": "先核对持仓", "watch_zone": "等待企稳",
               "stabilization": "企稳待确认", "conclusion": "核对最新报价", "events": []},
        "decision": {
            "status": "review", "title": "核对条件后再考虑调整", "summary": "先核对当前报价与可用股数。",
            "data_as_of": "2026-09-21", "quote_time": "2026-09-21 10:15:00", "technical_as_of": "2026-09-18",
            "eligible_for_alert": True, "blockers": [],
            "actions": [{"category": "buy", "direction": "买入观察", "shares": 100,
                         "reason": "进入观察区且企稳信号达到阈值", "price_range": "42 至 44 元",
                         "current_shares": 500, "shares_after": 600, "signal": "企稳确认",
                         "when": "交易时段内条件满足后", "checks": ["核对可用资金", "核对当前价格"],
                         "invalidation": "离开观察区或风险升高时暂缓"}],
            "schedule": [{"time": "09:30–11:30", "task": "观察最新报价和条件变化"}],
            "scenarios": [{"title": "继续等待企稳", "condition": "价格仍在观察区",
                           "action": "核对企稳信号", "invalidation": "报价过期时暂缓"}],
            "checkpoints": ["成交后更新持仓记录"],
        },
    }


def dashboard(report):
    environment = Environment(
        loader=FileSystemLoader(ROOT / "app/web/templates"),
        autoescape=select_autoescape(["html"]),
    )
    return environment.get_template("dashboard_synology.html").render(
        r=report, p=report_fixture()["portfolio"], reports=[], triggers=[], version="test"
    )


class ActiveContent(HTMLParser):
    def __init__(self):
        super().__init__()
        self.unsafe = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"img", "iframe", "object"} or (tag == "script" and not attrs.get("src", "").startswith("/static/")):
            self.unsafe.append(tag)
        if any(name.startswith("on") for name in attrs):
            self.unsafe.append("event-handler")
        if any(value and value.lower().startswith("javascript:") for value in attrs.values()):
            self.unsafe.append("javascript-url")


def test_dashboard_shows_when_amount_checks_and_honest_ai_status():
    page = dashboard(report_fixture())
    for content in ("现在该做什么", "100 股", "500 → 600 股", "42 至 44 元", "交易时段内条件满足后",
                    "09:30–11:30", "核对可用资金", "指标基准日", "2026-09-18", "程序规则解读 · AI 未生成",
                    "模型请求超时", "展开规则解读", "需人工确认后操作"):
        assert content in page
    assert "AI 已生成" not in page


def test_dashboard_handles_no_report_and_legacy_report():
    assert "先更新行情，生成操作计划" in dashboard(None)
    report = report_fixture()
    del report["decision"]
    report["ai"] = {"status": "unavailable", "summary": "旧报告"}
    assert "旧报告" in dashboard(report)
    assert "更新后显示具体观察条件" in dashboard(report)


def test_dashboard_action_text_is_escaped():
    report = report_fixture()
    payload = '<img src=x onerror=alert(1)><script>alert(2)</script>'
    report["decision"]["title"] = payload
    report["decision"]["summary"] = payload
    report["decision"]["actions"][0]["reason"] = payload
    report["decision"]["actions"][0]["checks"] = [payload]
    report["decision"]["blockers"] = [payload]
    report["ai"]["reason"] = payload
    page = dashboard(report)
    parser = ActiveContent()
    parser.feed(page)
    assert not parser.unsafe
    assert "&lt;img" in page


def test_report_starts_with_plan_and_labels_historical_snapshot(tmp_path):
    md, page = render_reports(report_fixture(), tmp_path)
    text = md.read_text()
    rendered = page.read_text()
    assert text.index("## 先看操作计划") < text.index("## 一、今日行情")
    for content in ("100 股（参考计划）", "500 → 600 股", "09:30–11:30", "报价过期时暂缓",
                    "程序规则解读（AI 未生成）", "模型请求超时", "历史报告中的条件可能已失效"):
        assert content in text
    assert 'href="/"' in rendered
    assert "历史日报 · 静态快照" in rendered
    assert "生成日期：2026-09-21 · 行情日期：2026-09-18" in rendered


def test_report_plan_rejects_html_and_markdown_injection(tmp_path):
    report = deepcopy(report_fixture())
    payload = '```html\n<script>alert(1)</script>\n```\n![x](javascript:alert(1))'
    report["decision"]["summary"] = payload
    report["decision"]["actions"][0]["reason"] = '<img src="x" onerror="alert(1)">'
    report["decision"]["checkpoints"] = ['[danger](javascript:alert(1))']
    _, page = render_reports(report, tmp_path)
    parser = ActiveContent()
    parser.feed(page.read_text())
    assert not parser.unsafe


def test_legacy_report_has_clear_path_to_current_plan(tmp_path):
    report = report_fixture()
    report.pop("decision")
    _, page = render_reports(report, tmp_path)
    assert "本报告未包含操作计划" in page.read_text()
    assert 'href="/"' in page.read_text()
