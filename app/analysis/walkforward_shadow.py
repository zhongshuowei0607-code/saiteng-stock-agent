"""Research-only walk-forward shadow account.

The live report keeps its fixed zones. This module maintains a separate paper
account using zones recalibrated from a rolling training window, so the user can
watch the research suggestion without changing the live plan.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from app.analysis.action_plan import build_action_guide
from app.analysis.risk_analyzer import risk_score
from app.backtest.engine import calibrate_zones
from app.config.settings import Settings
from app.database.repository import Repository
from app.portfolio.portfolio_service import load_position, watch_state

TZ = ZoneInfo("Asia/Shanghai")
STATE_VERSION = 1
DEFAULT_TRAIN_DAYS = 250
DEFAULT_REBALANCE_DAYS = 60
HISTORY_LIMIT = 250


def state_path(root: Path) -> Path:
    return root / "data/walkforward_shadow.json"


def load_shadow(root: Path) -> dict | None:
    path = state_path(root)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (ValueError, OSError):
        return None


def _save(root: Path, state: dict) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as temporary:
        json.dump(state, temporary, ensure_ascii=False, indent=2)
        name = temporary.name
    Path(name).replace(path)


def _fees(amount: float, side: str) -> float:
    commission = max(5.0, amount * 0.0003)
    stamp = amount * 0.0005 if side == "sell" else 0.0
    return commission + stamp


def _valuation(shares: int, average_cost: float, maximum: int, price: float) -> dict:
    cost = average_cost * shares
    value = max(0.0, price * shares)
    pnl = value - cost
    return {
        "shares": shares,
        "total_cost": round(cost, 2),
        "average_cost": round(average_cost, 4),
        "market_value": round(value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl / cost * 100, 2) if cost else None,
        "max_shares": maximum,
        "remaining_shares": max(0, maximum - shares),
        "position_ratio": shares / maximum if maximum else 0,
        "over_limit": shares > maximum,
    }


def _price_zone(zones: list[dict], price: float) -> str | None:
    for zone in zones:
        low, high = zone.get("min"), zone.get("max")
        if (low is None or price >= low) and (high is None or price < high):
            return zone.get("label")
    return None


def _bars_since(technical, date: str | None) -> int:
    if not date or technical.empty:
        return 10**9
    return int((technical["date"].astype(str) > date).sum())


def summarize_shadow(state: dict | None) -> dict | None:
    return _summary(state, {}) if state else None


def _summary(state: dict, report: dict) -> dict:
    snapshot = (state.get("history") or [{}])[-1]
    return {
        "calibrated_on": state.get("calibrated_on"),
        "train_days": state.get("train_days", DEFAULT_TRAIN_DAYS),
        "rebalance_days": state.get("rebalance_days", DEFAULT_REBALANCE_DAYS),
        "zones": state.get("zones", []),
        "current_zone": snapshot.get("current_zone"),
        "event_risk": snapshot.get("event_risk", False),
        "portfolio": state.get("portfolio", {}),
        "performance": state.get("performance", {}),
        "last_action": snapshot.get("action"),
        "last_snapshot_date": snapshot.get("date"),
        "note": "研究用途，不自动覆盖上方操作计划和固定观察区。",
    }


def _build_shadow(
    report: dict,
    zones: list[dict],
    portfolio: dict,
    settings: Settings,
) -> dict:
    shadow = deepcopy(report)
    shadow["portfolio"] = portfolio
    shadow["position_zones"] = zones
    shadow["watch_zone"] = watch_state(
        report.get("market", {}).get("close"),
        report.get("stabilization", {}),
        {**settings.strategy, "zones": zones},
        event_stop=any(
            item.get("stop_adding_observation") is True
            for item in report.get("ai", {}).get("events", [])
        ),
    )
    shadow["risk"] = risk_score(shadow)
    shadow["decision"] = build_action_guide(shadow)
    return shadow


def update_shadow(
    settings: Settings,
    report: dict,
    technical,
    repository: Repository | None = None,
    root: Path | None = None,
    train_days: int = DEFAULT_TRAIN_DAYS,
    rebalance_days: int = DEFAULT_REBALANCE_DAYS,
) -> dict:
    root = root or settings.root
    state = load_shadow(root) or {}
    date = str(report.get("market", {}).get("date") or report.get("date") or "")
    price = float(report.get("market", {}).get("close") or 0)
    if not date or price <= 0 or technical is None or technical.empty:
        return _summary(state, report)

    if state.get("last_snapshot_date") == date:
        return _summary(state, report)

    due = (
        not state.get("zones")
        or _bars_since(technical, state.get("calibrated_on")) >= int(
            state.get("rebalance_days", rebalance_days)
        )
    )
    if due:
        training = technical.tail(max(30, train_days))
        state["zones"] = calibrate_zones(training)
        state["calibrated_on"] = date
        state["training_start"] = str(training.iloc[0]["date"])
        state["training_bars"] = len(training)
        state["train_days"] = train_days
        state["rebalance_days"] = rebalance_days
        state["version"] = STATE_VERSION

    portfolio = state.get("portfolio")
    if not portfolio:
        actual = load_position(settings.path("data/portfolio.json"))
        actual_value = actual.valuation(price)
        maximum = actual.max_shares
        shares = int(actual_value.get("shares") or 0)
        average_cost = float(actual_value.get("average_cost") or 0.0)
        cash = 0.0 if shares else maximum * price
        portfolio = {
            "shares": shares,
            "cash": round(cash, 2),
            "average_cost": round(average_cost, 4),
            "max_shares": maximum,
        }
        state["portfolio"] = portfolio
        state["start_date"] = date
        state["initial_price"] = price
        state["initial_equity"] = round(cash + shares * price, 2)
        state["benchmark_initial_price"] = price
        state["benchmark_shares"] = shares or maximum
        state["benchmark_initial_equity"] = round(
            shares * price if shares else maximum * price, 2
        )

    maximum = int(portfolio.get("max_shares") or 0)
    shares = int(portfolio.get("shares") or 0)
    cash = float(portfolio.get("cash") or 0.0)
    average_cost = float(portfolio.get("average_cost") or 0.0)
    valuation = _valuation(shares, average_cost, maximum, price)
    shadow = _build_shadow(report, state["zones"], valuation, settings)
    action = (shadow.get("decision") or {}).get("actions") or []
    action = action[0] if action else None
    executed = None
    if action:
        side = "buy" if action.get("category") == "buy" else "sell"
        quantity = int(action.get("shares") or 0)
        fee = 0.0
        if side == "buy":
            quantity = min(quantity, max(0, maximum - shares))
            quantity = quantity // 100 * 100
            while quantity > 0:
                amount = quantity * price
                fee = _fees(amount, "buy")
                if amount + fee <= cash:
                    break
                quantity -= 100
            if quantity > 0:
                amount = quantity * price
                fee = _fees(amount, "buy")
                cash -= amount + fee
                average_cost = (
                    (average_cost * shares + amount + fee) / (shares + quantity)
                )
                shares += quantity
            else:
                fee = 0.0
                executed = None
        else:
            quantity = min(quantity, shares)
            if quantity > 0:
                amount = quantity * price
                fee = _fees(amount, "sell")
                cash += amount - fee
                shares -= quantity
                if shares == 0:
                    average_cost = 0.0
            else:
                executed = None
        if quantity > 0:
            executed = {
                "date": date,
                "side": side,
                "shares": quantity,
                "price": round(price, 4),
                "fee": round(fee, 2),
                "signal": action.get("signal"),
                "reason": action.get("reason", ""),
                "fill_basis": "当日收盘（纸面）",
            }
        portfolio.update(
            {
                "shares": shares,
                "cash": round(cash, 2),
                "average_cost": round(average_cost, 4),
            }
        )

    control_risk = any(
        "控制权变更" in (row.get("categories") or [])
        for key in ("announcements", "news")
        for row in report.get(key, [])
    )
    equity = round(cash + shares * price, 2)
    initial_equity = float(state.get("initial_equity") or equity)
    benchmark_price = float(state.get("benchmark_initial_price") or price)
    benchmark_shares = int(state.get("benchmark_shares") or 0)
    benchmark_value = round(
        benchmark_shares * price
        + max(0.0, float(state.get("initial_equity") or 0) - benchmark_shares * benchmark_price),
        2,
    )
    performance = {
        "initial_equity": round(initial_equity, 2),
        "equity": equity,
        "return_pct": round((equity / initial_equity - 1) * 100, 2)
        if initial_equity
        else None,
        "benchmark_return_pct": round((benchmark_value / initial_equity - 1) * 100, 2)
        if initial_equity
        else None,
        "start_date": state.get("start_date"),
    }
    state["performance"] = performance
    snapshot = {
        "date": date,
        "close": round(price, 4),
        "current_zone": _price_zone(state.get("zones", []), price)
        or shadow.get("watch_zone", {}).get("state"),
        "event_risk": bool(shadow.get("watch_zone", {}).get("event_stop")) or control_risk,
        "shadow_shares": shares,
        "shadow_cash": round(cash, 2),
        "shadow_equity": equity,
        "shadow_return_pct": performance["return_pct"],
        "benchmark_return_pct": performance["benchmark_return_pct"],
        "action": executed,
    }
    history = state.setdefault("history", [])
    history.append(snapshot)
    state["history"] = history[-HISTORY_LIMIT:]
    state["last_snapshot_date"] = date
    state["updated_at"] = datetime.now(TZ).isoformat()
    _save(root, state)
    return _summary(state, report)
