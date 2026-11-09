"""Build a read-only current view without rewriting a historical report."""

from copy import deepcopy
from .action_plan import build_action_guide
from .risk_analyzer import risk_score
from app.portfolio.portfolio_service import load_position, watch_state
from app.portfolio.risk_budget import build_risk_budget


def current_action_report(settings, report, monitor=None):
    view = deepcopy(report or {})
    live = monitor.snapshot() if monitor is not None else None
    if live and live.get("generated_at") == view.get("generated_at"):
        view = live
        if monitor.stale_data:
            view["stale_data"] = True
    view["action_plan"] = settings.strategy.get("action_plan", {})
    view["position_zones"] = settings.strategy.get("zones", [])
    view["confirmation_score"] = settings.strategy.get("confirmation_score", 7)
    view["risk_config"] = settings.config.get("risk", {})
    view["schedule_config"] = settings.config.get("scheduler", {})
    view["monitor_interval_seconds"] = settings.config.get("monitor", {}).get("interval_seconds", 180)
    price = view.get("market", {}).get("close")
    view["portfolio"] = load_position(settings.path("data/portfolio.json")).valuation(price)
    view["risk_budget"] = build_risk_budget(
        view["portfolio"], view.get("technical") or {}
    )
    view["strategy_version"] = "v1"
    breakout = bool(view.get("breakout_confirmed"))
    view["watch_zone"] = watch_state(price, view.get("stabilization", {}), settings.strategy,
        resistance={"breakout_confirmed": breakout},
        event_stop=any(e.get("stop_adding_observation") is True for e in view.get("ai", {}).get("events", [])))
    view["risk"] = risk_score(view)
    view["decision"] = build_action_guide(view)
    return view
