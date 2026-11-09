from pathlib import Path

import pandas as pd

from app.backtest.engine import (
    BacktestConfig,
    run_backtest,
    run_walk_forward,
    save_backtest,
)
from app.config.settings import load_settings
from app.database.db import create_db
from app.database.repository import Repository


def bars(days=80, price=10.0):
    dates = pd.bdate_range("2026-01-05", periods=days)
    rows = []
    previous = price
    for i, date in enumerate(dates):
        close = price + (i % 3) * 0.05
        rows.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": previous,
                "close": close,
                "high": max(previous, close) + 0.1,
                "low": min(previous, close) - 0.1,
                "pre_close": previous,
                "change": close - previous,
                "pct_change": (close / previous - 1) * 100,
                "volume": 1000,
                "amount": 1000 * close,
                "source": "synthetic-qfq",
            }
        )
        previous = close
    return pd.DataFrame(rows)


def test_backtest_runs_on_adjusted_bars_and_respects_max_shares(tmp_path):
    repository = Repository(create_db(tmp_path / "stock_agent.db"))
    repository.save_adjusted_bars("603283.SH", bars())
    result = run_backtest(
        load_settings(),
        repository,
        BacktestConfig(
            code="603283.SH",
            max_shares=1000,
            initial_shares=1000,
            initial_cash=0,
            warmup_bars=30,
        ),
    )
    summary = result["summary"]
    assert summary["data_basis"] == "qfq"
    assert summary["trades"] >= 1
    assert summary["final_shares"] <= 1000
    assert summary["final_shares"] % 100 == 0
    assert summary["final_cash"] >= 0
    md, js = save_backtest(result, tmp_path)
    assert md.is_file() and js.is_file()


def test_walk_forward_recalibrates_zones_and_runs(tmp_path):
    repository = Repository(create_db(tmp_path / "stock_agent.db"))
    repository.save_adjusted_bars("603283.SH", bars(days=120))
    result = run_walk_forward(
        load_settings(),
        repository,
        BacktestConfig(code="603283.SH", max_shares=1000, warmup_bars=30),
        train_days=30,
        rebalance_days=20,
    )
    summary = result["summary"]
    assert summary["walk_forward"] is True
    assert summary["rebalances"] >= 1
    assert summary["data_basis"] == "qfq"
    assert "walk-forward" in " ".join(summary["warnings"])


def test_calibrated_zones_are_contiguous():
    from app.backtest.engine import calibrate_zones

    frame = bars(days=120)
    from app.indicators.technical import calculate

    zones = calibrate_zones(calculate(frame))
    assert zones[0]["min"] is None and zones[-1]["max"] is None
    for left, right in zip(zones, zones[1:]):
        assert left["max"] == right["min"]
        assert left["max"] < right["min"] or left["max"] == right["min"]
    assert all(zone["min"] is None or zone["max"] is None or zone["min"] < zone["max"] for zone in zones)


def test_backtest_rejects_short_history(tmp_path):
    repository = Repository(create_db(tmp_path / "stock_agent.db"))
    repository.save_adjusted_bars("603283.SH", bars(days=20))
    try:
        run_backtest(
            load_settings(),
            repository,
            BacktestConfig(code="603283.SH", warmup_bars=30),
        )
    except ValueError as exc:
        assert "行情不足" in str(exc)
    else:
        raise AssertionError("expected ValueError")
