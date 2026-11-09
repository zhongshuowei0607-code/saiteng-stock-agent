import pytest

from app.portfolio.position import Buy, Position
from app.portfolio.risk_budget import build_risk_budget


def position(**kwargs):
    return Position(
        code="603283.SH",
        max_shares=kwargs.pop("max_shares", 1100),
        buys=[Buy(price=41.374, shares=kwargs.pop("shares", 1100))],
        **kwargs,
    )


def test_position_exposes_account_and_available_fields():
    p = position(
        account_equity=100000,
        cash=50000,
        available_shares=700,
        risk_per_trade_pct=1.0,
        atr_stop_multiplier=2.0,
    )
    v = p.valuation(35.31)
    assert v["account_equity"] == 100000
    assert v["cash"] == 50000
    assert v["available_shares"] == 700
    assert v["risk_per_trade_pct"] == 1.0
    assert v["atr_stop_multiplier"] == 2.0


def test_available_shares_are_clamped_to_holding():
    p = position(account_equity=100000, cash=0, available_shares=1500)
    assert p.valuation(35.31)["available_shares"] == 1100


def test_risk_budget_flags_over_budget_and_blocks_add():
    p = position(account_equity=100000, cash=50000, available_shares=700)
    v = p.valuation(35.31)
    rb = build_risk_budget(v, {"close": 35.31, "ATR": 2.0})
    assert rb["risk_budget_shares"] == 200  # 1% * 100k / (2*2) = 250 -> 200
    assert rb["current_risk_pct"] == 4.4
    assert rb["status"] == "over_budget"
    assert rb["max_add_by_risk"] == 0
    assert rb["max_add_by_cap"] == 0
    assert rb["max_add_shares"] == 0


def test_risk_budget_allows_incremental_position():
    p = position(shares=100, account_equity=100000, cash=50000)
    v = p.valuation(35.31)
    rb = build_risk_budget(v, {"close": 35.31, "ATR": 2.0})
    assert rb["risk_budget_shares"] == 200
    assert rb["current_risk_pct"] == 0.4
    assert rb["status"] == "within"
    assert rb["max_add_by_risk"] == 100
    assert rb["max_add_by_cash"] == 1400
    assert rb["max_add_by_cap"] == 1000
    assert rb["max_add_shares"] == 100


def test_missing_equity_and_atr_are_surfaced():
    p = position(account_equity=None, cash=None, available_shares=None)
    v = p.valuation(35.31)
    assert v["account_equity_source"] == "market_value_fallback"
    rb = build_risk_budget(v, {"close": 35.31, "ATR": None})
    assert "account_equity" in rb["missing"]
    assert "available_shares" in rb["missing"]
    assert "ATR" in rb["missing"]
    assert rb["stop_distance"] is None
    assert rb["max_add_shares"] is None
