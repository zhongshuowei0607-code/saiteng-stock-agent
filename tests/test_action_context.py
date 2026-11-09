from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from app.analysis.action_context import current_action_report
from app.analysis.action_plan import build_action_guide
from app.config.settings import load_settings

from test_action_plan import NOW, report


def test_configured_max_shares_controls_capacity_not_a_fixed_1000():
    facts = report()
    facts["portfolio"] = {"shares": 500, "max_shares": 1100}
    facts["position_zones"] = [{"label": "第一加仓观察区", "min": 42, "max": 43}]
    facts["watch_zone"] = {"state": "第一加仓观察区", "confirmed": True}
    guide = build_action_guide(facts, NOW)
    action = guide["actions"][0]
    assert action["shares"] == 300
    assert action["shares_after"] == 800
    assert "上限 1100 股" in " ".join(guide["checkpoints"])

    facts["portfolio"]["shares"] = 1100
    guide = build_action_guide(facts, NOW)
    assert not guide["actions"]
    assert any("剩余额度不足一手" in item for item in guide["blockers"])


def test_critical_risk_exits_all_shares_including_odd_lot():
    facts = report()
    facts["portfolio"] = {"shares": 1050, "max_shares": 1100}
    facts["risk"]["score"] = 86
    guide = build_action_guide(facts, NOW)
    assert [a["category"] for a in guide["actions"]] == ["risk"]
    assert guide["actions"][0]["shares"] == 1050
    assert guide["actions"][0]["shares_after"] == 0


def test_sell_quantities_respect_board_lots_and_odd_lot_rule():
    facts = report()
    facts["portfolio"] = {"shares": 1050, "max_shares": 1100}
    facts["position_zones"] = [{"label": "反弹观察区", "min": 42, "max": 43}]
    facts["watch_zone"] = {"state": "反弹观察区"}
    action = build_action_guide(facts, NOW)["actions"][0]
    assert action["shares"] == 200  # 20% of 1050 -> 210 -> 200
    assert action["shares_after"] == 850
    assert any("100 股整数倍" in text for text in action["checks"])

    facts["portfolio"]["shares"] = 50
    action = build_action_guide(facts, NOW)["actions"][0]
    assert action["shares"] == 50 and action["shares_after"] == 0


def test_event_stop_blocks_adds_without_forcing_a_sale():
    facts = report()
    facts["watch_zone"] = {"state": "高风险区", "event_stop": True}
    facts["risk"]["score"] = 40
    facts["stabilization"]["score"] = 8
    guide = build_action_guide(facts, NOW)
    assert not guide["actions"]
    assert guide["state"] == "事件风险"
    assert any("重大事件" in item for item in guide["blockers"])


def test_current_action_report_preserves_confirmed_breakout(tmp_path):
    settings = load_settings()
    (tmp_path / "data").mkdir()
    (tmp_path / "data/portfolio.json").write_text(
        json.dumps({"code": "603283.SH", "max_shares": 1100, "buys": [{"price": 42, "shares": 500}], "sells": []}),
        encoding="utf-8",
    )
    view_settings = SimpleNamespace(
        strategy=settings.strategy,
        config=settings.config,
        path=lambda name: tmp_path / name,
    )
    facts = report()
    facts["breakout_confirmed"] = True
    facts["watch_zone"] = {"state": "第一加仓观察区", "confirmed": True}
    view = current_action_report(view_settings, facts)
    assert view["watch_zone"]["state"] == "突破确认区"
    assert view["decision"]["state"] == "突破确认区"
