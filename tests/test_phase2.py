import numpy as np
import pandas as pd
import pytest
from app.indicators.technical import calculate, rsi
from app.indicators.support_resistance import levels
from app.indicators.stabilization import stabilization
from app.indicators.trend import trends
from app.portfolio.position import Buy, Position
from app.portfolio.portfolio_service import watch_state
from app.config.settings import load_settings


def sample(n=300):
    close = np.arange(1, n + 1, dtype=float) + 30
    return pd.DataFrame(
        dict(
            date=pd.date_range("2025-01-01", periods=n).strftime("%Y-%m-%d"),
            open=close - 0.5,
            close=close,
            high=close + 1,
            low=close - 1,
            pre_close=close - 1,
            volume=np.full(n, 100.0),
            amount=close * 10000,
            pct_change=100 / (close - 1),
        )
    )


def test_ma_macd():
    frame = sample()
    df = calculate(frame)
    assert df.MA5.iloc[-1] == frame.close.tail(5).mean()
    assert df.MA250.iloc[:249].isna().all()
    # 手工递推 EMA 对照，独立验证 MACD 数值口径。
    fast = slow = frame.close.iloc[0]
    signal = 0
    for x in frame.close.iloc[1:]:
        fast += 2 / 13 * (x - fast)
        slow += 2 / 27 * (x - slow)
        signal += 0.2 * (fast - slow - signal)
    assert df.MACD.iloc[-1] == pytest.approx(2 * (fast - slow - signal))


def test_rsi_limits():
    assert rsi(pd.Series(range(40), dtype=float), 14).iloc[-1] == 100
    assert rsi(pd.Series(range(40, 0, -1), dtype=float), 14).iloc[-1] == 0
    assert rsi(pd.Series([20.0] * 40), 14).iloc[-1] == 50
    assert rsi(pd.Series([20.0] * 5), 14).isna().all()


def test_levels_trend():
    df = calculate(sample())
    result = levels(df)
    assert result["support"]
    assert all(x["price"] < df.close.iloc[-1] for x in result["support"])
    assert all(x["price"] > df.close.iloc[-1] for x in result["resistance"])
    assert trends(df)["long"]["state"] == "STRONG_BULL"
    assert trends(df.head(10))["short"]["state"] is None


def test_position():
    p = Position(
        code="603283.SH",
        max_shares=1000,
        buys=[dict(price=50, shares=200), dict(price=48, shares=200)],
    )
    v = p.valuation(45)
    assert (v["shares"], v["average_cost"], v["remaining_shares"]) == (400, 49, 600)
    assert v["pnl"] == -1600 and v["pnl_pct"] == pytest.approx(-1600 / 19600 * 100)
    assert p.valuation(None)["pnl"] is None


def test_trade_price_precision_and_share_integer():
    trade = Buy(price=49.625, shares=500)
    assert str(trade.price) == "49.625" and trade.shares == 500
    with pytest.raises(ValueError):
        Buy(price=49.6254, shares=500)
    with pytest.raises(ValueError):
        Buy(price=49.625, shares=500.5)


@pytest.mark.parametrize(
    "price,state",
    [
        (40.49, "高风险区"),
        (40.5, "第二加仓观察区"),
        (42, "第一加仓观察区"),
        (43, "持仓观察"),
        (46, "反弹观察区"),
        (48, "反弹减仓观察区"),
    ],
)
def test_state_boundaries(price, state):
    result = watch_state(price, {"score": 3}, load_settings().strategy)
    assert result["state"] == state and not result["confirmed"]
    if "加仓" in state:
        assert "不足" in result["message"]


def test_stabilization():
    df = calculate(sample())
    result = stabilization(df)
    assert len(result["signals"]) == 10 and 0 <= result["score"] <= 10
    assert result["score"] == sum(s["confirmed"] for s in result["signals"])
    assert stabilization(df.head(10))["score"] is None
    falling = sample()
    falling["close"] = falling.close[::-1].to_numpy()
    falling["open"] = falling.close + 0.5
    falling["high"] = falling.close + 1
    falling["low"] = falling.close - 1
    result = stabilization(calculate(falling))
    assert result["level"] == "LOW"
