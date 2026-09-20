from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.analysis.action_plan import build_action_guide, quote_is_fresh

NOW = datetime(2026, 9, 21, 10, tzinfo=ZoneInfo("Asia/Shanghai"))


def report():
    return {
        "market": {"close": 42.5, "date": "2026-09-21", "quote_time": NOW.isoformat(), "is_realtime": True},
        "portfolio": {"shares": 500, "max_shares": 1000},
        "stabilization": {"score": 8}, "confirmation_score": 7,
        "risk": {"score": 40}, "risk_config": {"warning_threshold": 65},
        "watch_zone": {"state": "第一加仓观察区", "confirmed": True},
        "position_zones": [{"label": "第一加仓观察区", "min": 42, "max": 43}],
        "levels": {"support": [{"price": 41}], "resistance": [{"price": 43}]},
        "baseline_current": True, "trading_session_open": True, "stale_data": False,
    }


def test_confirmed_add_uses_capacity_and_lots_without_mutating_facts():
    facts = report()
    before = deepcopy(facts)
    guide = build_action_guide(facts, NOW)
    assert guide["status"] == "review"
    assert guide["eligible_for_alert"]
    assert [(a["category"], a["shares"], a["shares_after"]) for a in guide["actions"]] == [("buy", 200, 700)]
    assert facts == before


def test_unconfirmed_add_or_unknown_risk_never_buys():
    facts = report()
    facts["stabilization"]["score"] = 3
    assert not build_action_guide(facts, NOW)["actions"]
    facts["stabilization"]["score"] = 8
    facts["risk"]["score"] = None
    assert not build_action_guide(facts, NOW)["actions"]


def test_risk_and_support_override_a_buy_zone():
    facts = report()
    facts["risk"]["score"] = 70
    guide = build_action_guide(facts, NOW)
    assert [a["category"] for a in guide["actions"]] == ["risk"]
    assert guide["actions"][0]["shares"] < facts["portfolio"]["shares"]
    facts["risk"]["score"] = 40
    facts["levels"]["support"][0]["price"] = 42.6
    assert [a["signal"] for a in build_action_guide(facts, NOW)["actions"]] == ["BREAK_SUPPORT"]


@pytest.mark.parametrize("minutes", [-1, 7, 1440])
def test_old_or_future_quote_is_never_actionable(minutes):
    facts = report()
    facts["market"]["quote_time"] = (NOW - timedelta(minutes=minutes)).isoformat()
    assert not quote_is_fresh(facts, NOW)
    assert not build_action_guide(facts, NOW)["eligible_for_alert"]


def test_same_date_without_timestamp_is_only_a_plan():
    facts = report()
    facts["market"].pop("quote_time")
    guide = build_action_guide(facts, NOW)
    assert guide["actions"] and not guide["eligible_for_alert"]
    assert guide["status"] == "wait"
    assert "下一交易时段" in guide["actions"][0]["when"]


def test_calendar_and_baseline_gate_alerts():
    facts = report()
    facts["trading_session_open"] = False
    assert not build_action_guide(facts, NOW)["eligible_for_alert"]
    facts["trading_session_open"] = True
    facts["baseline_current"] = False
    guide = build_action_guide(facts, NOW)
    assert not guide["eligible_for_alert"] and not guide["actions"]


def test_fraction_limits_never_exceed_capacity_or_raise_zero_to_one_lot():
    facts = report()
    facts["action_plan"] = {"first_add_fraction": 20}
    assert build_action_guide(facts, NOW)["actions"][0]["shares"] == 500
    facts["action_plan"]["first_add_fraction"] = 0.1
    assert not build_action_guide(facts, NOW)["actions"]
    facts["portfolio"]["shares"] = 1000
    assert not build_action_guide(facts, NOW)["actions"]


def test_sell_is_not_mistaken_for_known_available_inventory():
    facts = report()
    facts["position_zones"] = [{"label": "反弹观察区", "min": 42, "max": 43}]
    action = build_action_guide(facts, NOW)["actions"][0]
    assert action["shares"] == 100 and action["shares_after"] == 400
    assert any("T+1" in text for text in action["checks"])


def test_empty_report_still_explains_next_steps():
    guide = build_action_guide({}, NOW)
    assert guide["status"] == "blocked" and not guide["actions"]
    assert guide["blockers"] and guide["schedule"]
