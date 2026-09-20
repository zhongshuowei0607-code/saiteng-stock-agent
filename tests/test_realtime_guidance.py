from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import json

import pytest

from app.data.realtime_quote import parse_tencent_quote
from app.monitor.realtime import RealtimeMonitor
from test_action_plan import NOW, report


def test_quote_parser_uses_source_time_and_rejects_wrong_symbol():
    parts = [""] * 40
    for key, value in {2: "603283", 3: "47.36", 4: "45.93", 5: "46.80", 6: "147104", 30: "20260921100000", 33: "47.65", 34: "45.77", 38: "69106"}.items():
        parts[key] = value
    text = 'v_sh603283="' + "~".join(parts) + '";'
    quote = parse_tencent_quote(text)
    assert quote["quote_time"] == NOW.isoformat()
    assert quote["amount"] == 691060000
    assert quote["is_realtime"]
    with pytest.raises(ValueError):
        parse_tencent_quote(text.replace("v_sh603283", "v_sh600000"))
    with pytest.raises(ValueError):
        parse_tencent_quote(text.replace("20260921100000", "not-a-date"))


def setup_monitor(tmp_path, monkeypatch, baseline=date(2026, 9, 18)):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/portfolio.json").write_text(json.dumps({"code": "603283.SH", "max_shares": 1000, "buys": [{"price": 49, "shares": 500}]}))
    settings = SimpleNamespace(config={"monitor": {"interval_seconds": 180}, "risk": {"warning_threshold": 65, "critical_threshold": 85}}, strategy={"zones": report()["position_zones"], "confirmation_score": 7}, path=lambda path: tmp_path / path)
    daily = report()
    daily["market"] = {"date": baseline.isoformat(), "close": 42.5}
    daily["ai"] = {"status": "generated", "summary": "已有完整AI日报", "events": []}
    source = deepcopy(daily)

    class Repository:
        def reports(self, **kwargs):
            return [source]

        def save_report(self, *args):
            raise AssertionError("实时监控不能覆盖日报")

    class Analyzer:
        def analyze(self, **kwargs):
            raise AssertionError("实时监控不能禁用LLM后重跑日报")

    calls = []
    engine = SimpleNamespace(evaluate=lambda *args: calls.append(args))
    calendar = SimpleNamespace(is_open=lambda day: True, previous_open_day=lambda day: date(2026, 9, 18))
    monkeypatch.setattr("app.monitor.realtime.fetch_realtime_quote", lambda code: report()["market"])
    return RealtimeMonitor(settings, Repository(), Analyzer(), calendar, engine), source, calls


def test_live_monitor_keeps_daily_ai_and_levels_unchanged(tmp_path, monkeypatch):
    monitor, saved, calls = setup_monitor(tmp_path, monkeypatch)
    before = deepcopy(saved)
    assert monitor.poll(NOW)
    assert saved == before
    assert monitor.latest_report["ai"]["summary"] == "已有完整AI日报"
    assert monitor.latest_report["technical_as_of"] == "2026-09-18"
    assert len(calls) == 1
    assert monitor.latest_report["decision"]["eligible_for_alert"]


def test_old_quote_pauses_alerts_and_records_failure(tmp_path, monkeypatch):
    monitor, _, calls = setup_monitor(tmp_path, monkeypatch)
    quote = report()["market"]
    quote["quote_time"] = "2026-09-18T15:00:00+08:00"
    monkeypatch.setattr("app.monitor.realtime.fetch_realtime_quote", lambda code: quote)
    assert not monitor.poll(NOW)
    assert not calls and monitor.stale_data and monitor.last_error


def test_old_analysis_baseline_cannot_produce_actions(tmp_path, monkeypatch):
    monitor, _, _ = setup_monitor(tmp_path, monkeypatch, date(2026, 9, 9))
    assert monitor.poll(NOW)
    assert monitor.latest_report["baseline_current"] is False
    assert not monitor.latest_report["decision"]["eligible_for_alert"]


def test_disabled_monitor_never_fetches(tmp_path, monkeypatch):
    monitor, _, calls = setup_monitor(tmp_path, monkeypatch)
    monitor.settings.config["monitor"]["enabled"] = False
    assert not monitor.poll(NOW) and not calls
