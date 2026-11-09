from pathlib import Path

import pandas as pd

from app.data.market_provider import MarketService
from app.database.db import create_db
from app.database.repository import Repository


class FakeAdjustedProvider:
    source = "fake-qfq"

    def history(self, code, start, end, adjust=""):
        assert adjust == "qfq"
        return pd.DataFrame(
            [
                {
                    "date": "2026-10-19",
                    "open": 10.0,
                    "close": 10.5,
                    "high": 10.8,
                    "low": 9.9,
                    "pre_close": 10.0,
                    "change": 0.5,
                    "pct_change": 5.0,
                    "volume": 1000,
                    "amount": 1_000_000,
                    "source": "fake-qfq",
                },
                {
                    "date": "2026-10-20",
                    "open": 10.5,
                    "close": 11.0,
                    "high": 11.2,
                    "low": 10.4,
                    "pre_close": 10.5,
                    "change": 0.5,
                    "pct_change": 4.76,
                    "volume": 1200,
                    "amount": 1_200_000,
                    "source": "fake-qfq",
                },
            ]
        )


def _bars(days=80, close=10.0):
    dates = pd.bdate_range("2026-01-05", periods=days)
    return pd.DataFrame(
        [
            {
                "date": date.strftime("%Y-%m-%d"),
                "open": close,
                "close": close,
                "high": close + 0.2,
                "low": close - 0.2,
                "pre_close": close,
                "change": 0.0,
                "pct_change": 0.0,
                "volume": 1000,
                "amount": 1000 * close,
                "source": "fake",
            }
            for date in dates
        ]
    )


def test_analyzer_uses_qfq_for_technical_but_raw_for_market(tmp_path):
    from app.analysis.stock_analyzer import StockAnalyzer
    from app.bootstrap import bootstrap

    import shutil

    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copy("VERSION", tmp_path / "VERSION")
    settings, repository = bootstrap(tmp_path)
    repository.save_bars("603283.SH", _bars(close=10.0))
    repository.save_adjusted_bars("603283.SH", _bars(close=20.0))
    report = StockAnalyzer(settings, repository).analyze(
        "603283.SH", refresh=False, use_llm=False
    )
    assert report["technical_basis"] == "qfq"
    assert report["market"]["close"] == 10.0
    assert report["technical"]["close"] == 20.0
    assert "前复权" in " ".join(report["warnings"])


def test_adjusted_bars_are_stored_separately(tmp_path):
    repository = Repository(create_db(tmp_path / "stock_agent.db"))
    frame, warnings = MarketService([FakeAdjustedProvider()], repository).update_adjusted(
        "603283.SH", 800
    )
    assert len(frame) == 2
    assert warnings == []
    stored = repository.adjusted_history("603283.SH")
    assert len(stored) == 2
    assert float(stored.iloc[-1]["close"]) == 11.0
    assert stored.iloc[-1]["source"] == "fake-qfq"
    # Raw history must remain empty; the two series are intentionally separate.
    assert repository.history("603283.SH").empty
