"""Risk-budget calculation for Phase 0.

This is a research/visibility layer: it does not replace the v1 action plan.
It answers: given account equity, a per-trade risk budget and an ATR stop,
how much total exposure is justified, and how much can be added without
breaching the budget, cash or the configured share cap?
"""

from __future__ import annotations

from math import floor


def _number(value, default=None):
    try:
        result = float(value)
        return result if result == result else default
    except (TypeError, ValueError):
        return default


def build_risk_budget(portfolio: dict, technical: dict) -> dict:
    portfolio = portfolio or {}
    technical = technical or {}
    shares = max(0, int(_number(portfolio.get("shares"), 0) or 0))
    maximum = max(0, int(_number(portfolio.get("max_shares"), 0) or 0))
    price = _number(technical.get("close"))
    if price is None and portfolio.get("market_value") is not None and shares:
        price = _number(portfolio.get("market_value")) / shares
    atr = _number(technical.get("ATR"))
    equity = _number(portfolio.get("account_equity"))
    cash = _number(portfolio.get("cash"), 0.0) or 0.0
    risk_pct = _number(portfolio.get("risk_per_trade_pct"), 1.0) or 1.0
    atr_multiplier = _number(portfolio.get("atr_stop_multiplier"), 2.0) or 2.0
    missing = []
    if equity is None or portfolio.get("account_equity_source") != "configured":
        missing.append("account_equity")
    if not portfolio.get("available_shares_configured"):
        missing.append("available_shares")
    if portfolio.get("cash_source") == "missing_fallback":
        missing.append("cash")
    if atr is None:
        missing.append("ATR")
    if price is None:
        missing.append("price")

    stop_distance = atr * atr_multiplier if atr is not None else None
    risk_amount = equity * risk_pct / 100 if equity is not None else None
    target_total = (
        int(floor(risk_amount / stop_distance / 100.0) * 100)
        if risk_amount is not None and stop_distance and stop_distance > 0
        else None
    )
    max_add_by_risk = (
        max(0, target_total - shares) if target_total is not None else None
    )
    max_add_by_cash = (
        int(floor(cash / price / 100.0) * 100)
        if price and price > 0 and cash > 0
        else 0
    )
    max_add_by_cap = max(0, maximum - shares)
    max_add = (
        min(max_add_by_risk, max_add_by_cash, max_add_by_cap)
        if max_add_by_risk is not None
        else None
    )
    current_risk = shares * stop_distance if stop_distance is not None else None
    current_risk_pct = (
        current_risk / equity * 100
        if current_risk is not None and equity and equity > 0
        else None
    )
    if current_risk_pct is None:
        status = "unknown"
    elif current_risk_pct > risk_pct:
        status = "over_budget"
    elif current_risk_pct >= risk_pct * 0.95:
        status = "at_limit"
    else:
        status = "within"
    return {
        "account_equity": round(equity, 2) if equity is not None else None,
        "account_equity_source": portfolio.get("account_equity_source"),
        "cash": round(cash, 2),
        "available_shares": portfolio.get("available_shares", shares),
        "risk_per_trade_pct": round(risk_pct, 2),
        "risk_amount": round(risk_amount, 2) if risk_amount is not None else None,
        "atr": round(atr, 4) if atr is not None else None,
        "atr_stop_multiplier": round(atr_multiplier, 2),
        "stop_distance": round(stop_distance, 4) if stop_distance is not None else None,
        "stop_price": round(price - stop_distance, 2)
        if price is not None and stop_distance is not None
        else None,
        "risk_budget_shares": target_total,
        "current_risk_amount": round(current_risk, 2)
        if current_risk is not None
        else None,
        "current_risk_pct": round(current_risk_pct, 2)
        if current_risk_pct is not None
        else None,
        "max_add_by_risk": max_add_by_risk,
        "max_add_by_cash": max_add_by_cash,
        "max_add_by_cap": max_add_by_cap,
        "max_add_shares": max_add,
        "status": status,
        "missing": missing,
        "note": (
            "风险预算 = 账户权益 × 单笔风险% / (ATR × 止损倍数)，"
            "按 100 股向下取整；仅作为研究/风控参考，不构成交易指令。"
        ),
    }
