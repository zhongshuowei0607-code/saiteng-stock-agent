import json
import shutil

import pandas as pd
import pytest

from app.analysis.walkforward_shadow import load_shadow, update_shadow
from app.bootstrap import bootstrap
from app.indicators.stabilization import stabilization
from app.indicators.support_resistance import levels
from app.indicators.technical import calculate
from app.indicators.trend import trends


def bars(days=300, price=10.0):
    dates = pd.bdate_range("2025-01-02", periods=days)
    rows = []
    previous = price
    for i, date in enumerate(dates):
        close = price + (i % 20) * 0.05
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": previous,
                "close": close,
                "high": max(previous, close) + 0.2,
                "low": min(previous, close) - 0.2,
                "pre_close": previous,
                "change": close - previous,
                "pct_change": (close / previous - 1) * 100,
                "volume": 1000,
                "amount": 1000 * close,
                "source": "synthetic",
            }
        )
        previous = close
    return pd.DataFrame(rows)


def test_shadow_calibrates_once_per_market_date(tmp_path):
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copy("VERSION", tmp_path / "VERSION")
    settings, repository = bootstrap(tmp_path)
    frame = bars()
    technical = calculate(frame)
    last = technical.iloc[-1]
    price = float(last["close"])
    report = {
        "date": str(last["date"]),
        "market": {
            "date": str(last["date"]),
            "close": price,
            "open": float(last["open"]),
            "pre_close": float(last["pre_close"]),
            "pct_change": float(last["pct_change"]),
            "is_realtime": False,
        },
        "technical": {key: last[key] for key in ("close", "MA5", "MA20", "ATR", "RSI14")},
        "recent_closes": [float(value) for value in technical["close"].tail(5)],
        "trend": trends(technical),
        "levels": levels(technical),
        "stabilization": stabilization(technical),
        "portfolio": {"shares": 400, "max_shares": 1100, "average_cost": 10.0, "pnl_pct": 0},
        "risk": {"score": 40},
        "risk_config": {"warning_threshold": 65, "critical_threshold": 85},
        "confirmation_score": 7,
        "action_plan": settings.strategy.get("action_plan", {}),
        "position_zones": settings.strategy["zones"],
        "ai": {"events": []},
        "news": [],
        "announcements": [],
        "technical_as_of": str(last["date"]),
    }
    summary = update_shadow(settings, report, technical, root=tmp_path)
    assert summary["zones"] and len(summary["zones"]) == 6
    state = load_shadow(tmp_path)
    assert state["last_snapshot_date"] == str(last["date"])
    assert len(state["history"]) == 1
    again = update_shadow(settings, report, technical, root=tmp_path)
    assert len(load_shadow(tmp_path)["history"]) == 1
    assert again["last_snapshot_date"] == str(last["date"])
