"""Point-in-time backtest for the current deterministic action plan.

The backtest intentionally uses only prices/indicators and the configured
strategy. Historical news, announcements, fundamentals and valuation are not
reconstructed here; the result is a strategy/technical sanity check, not a
full simulation of the live report.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime
from math import sqrt
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import json
import pandas as pd

from app.analysis.action_plan import build_action_guide
from app.analysis.risk_analyzer import risk_score
from app.config.settings import Settings
from app.database.repository import Repository
from app.indicators.stabilization import stabilization
from app.indicators.support_resistance import levels
from app.indicators.technical import calculate
from app.indicators.trend import trends
from app.portfolio.portfolio_service import watch_state

TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class BacktestConfig:
    code: str = "603283.SH"
    start: str | None = None
    end: str | None = None
    max_shares: int = 1100
    initial_cash: float | None = None
    initial_shares: int = 0
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_bps: float = 2.0
    warmup_bars: int = 260
    limit_pct: float = 0.10
    lot_size: int = 100
    cooldown_days: int = 0


def _fees(amount: float, side: str, config: BacktestConfig) -> float:
    commission = max(config.min_commission, amount * config.commission_rate)
    stamp = amount * config.stamp_duty_rate if side == "sell" else 0.0
    return commission + stamp


def _position(
    shares: int, average_cost: float, max_shares: int, price: float
) -> dict:
    cost = average_cost * shares
    value = price * shares
    pnl = value - cost
    return {
        "shares": shares,
        "total_cost": round(cost, 4),
        "average_cost": round(average_cost, 4),
        "market_value": round(value, 4),
        "pnl": round(pnl, 4),
        "pnl_pct": round(pnl / cost * 100, 4) if cost else None,
        "max_shares": max_shares,
        "remaining_shares": max(0, max_shares - shares),
        "position_ratio": shares / max_shares if max_shares else 0,
        "over_limit": shares > max_shares,
    }


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def _facts(
    window: pd.DataFrame,
    shares: int,
    average_cost: float,
    config: BacktestConfig,
    settings: Settings,
    strategy: dict | None = None,
) -> dict:
    strategy = strategy or settings.strategy
    row = window.iloc[-1]
    price = float(row["close"])
    portfolio = _position(shares, average_cost, config.max_shares, price)
    market = {
        "date": str(row["date"]),
        "open": float(row["open"]),
        "close": price,
        "high": float(row["high"]),
        "low": float(row["low"]),
        "pre_close": float(row["pre_close"]),
        "pct_change": float(row["pct_change"]),
        "volume": float(row["volume"]),
        "amount": float(row["amount"]),
        "is_realtime": False,
    }
    technical = {
        key: (None if pd.isna(row[key]) else float(row[key]))
        for key in (
            "close",
            "MA5",
            "MA10",
            "MA20",
            "MA60",
            "MA120",
            "MA250",
            "RSI14",
            "MACD",
            "DIF",
            "DEA",
            "ATR",
            "volume_ratio",
        )
        if key in row
    }
    if "volume_signal" in row:
        technical["volume_signal"] = str(row["volume_signal"])
    stable = stabilization(window)
    facts: dict[str, Any] = {
        "date": str(row["date"]),
        "market": market,
        "technical": technical,
        "recent_closes": [float(value) for value in window["close"].tail(5)],
        "trend": trends(window),
        "portfolio": portfolio,
        "levels": levels(window),
        "stabilization": stable,
        "watch_zone": watch_state(price, stable, strategy),
        "risk": {},
        "risk_config": settings.config["risk"],
        "confirmation_score": strategy["confirmation_score"],
        "action_plan": strategy.get("action_plan", {}),
        "position_zones": strategy.get("zones", []),
        "schedule_config": settings.config["scheduler"],
        "technical_as_of": str(row["date"]),
        "baseline_current": True,
        "trading_session_open": False,
        "stale_data": False,
        "news": [],
        "announcements": [],
        "industry": {},
        "fundamental": {},
        "moneyflow": {},
        "ai": {},
    }
    facts["risk"] = risk_score(facts)
    return facts


def _equity(shares: int, cash: float, price: float) -> float:
    return cash + shares * price



def _zones_for(date: str, schedule: dict[str, list[dict]]) -> list[dict] | None:
    candidates = [key for key in schedule if key <= date]
    return schedule[max(candidates)] if candidates else None


def calibrate_zones(window: pd.DataFrame) -> list[dict]:
    """Build absolute price bands from a training window only.

    The calibration is deliberately simple and reproducible: strong support,
    first resistance and ATR define the boundaries. It has no future data.
    """
    row = window.iloc[-1]
    close = float(row["close"])
    atr = float(row["ATR"]) if pd.notna(row.get("ATR")) else close * 0.02
    atr = max(atr, close * 0.005)
    found = levels(window)
    supports = [
        item for item in found.get("support", [])
        if item.get("price") is not None
    ]
    support_item = max(
        supports,
        key=lambda item: (float(item.get("strength", 0)), -float(item["price"])),
        default=None,
    ) if supports else None
    support = (
        float(support_item["price"]) if support_item else close - 1.5 * atr
    )
    support = min(support, close - 0.1 * atr)
    resistance = (
        float(found["resistance"][0]["price"])
        if found.get("resistance")
        else close + 1.5 * atr
    )
    resistance = max(resistance, support + 0.5 * atr)
    b0 = max(0.01, support - 0.5 * atr)
    b1 = max(b0 + 0.01, support)
    b2 = b1 + 0.5 * atr
    b3 = max(resistance, b2 + 0.25 * atr)
    b4 = b3 + 1.0 * atr
    if not (b0 < b1 < b2 < b3 < b4):
        b0, b1, b2, b3, b4 = (
            close - 1.5 * atr,
            close - 1.0 * atr,
            close - 0.5 * atr,
            close + 0.5 * atr,
            close + 1.5 * atr,
        )
    return [
        {"min": None, "max": b0, "label": "高风险区"},
        {"min": b0, "max": b1, "label": "第二加仓观察区"},
        {"min": b1, "max": b2, "label": "第一加仓观察区"},
        {"min": b2, "max": b3, "label": "持仓观察"},
        {"min": b3, "max": b4, "label": "反弹观察区"},
        {"min": b4, "max": None, "label": "反弹减仓观察区"},
    ]


def run_walk_forward(
    settings: Settings,
    repository: Repository,
    config: BacktestConfig | None = None,
    train_days: int = 250,
    rebalance_days: int = 60,
) -> dict:
    """Recalibrate zones on a rolling training window, then trade out of sample."""
    config = config or BacktestConfig()
    frame = repository.adjusted_history(config.code)
    basis = "qfq"
    warnings: list[str] = []
    if frame.empty:
        frame = repository.history(config.code)
        basis = "raw"
        warnings.append("前复权数据不可用，walk-forward 使用不复权价格。")
    if frame.empty:
        raise ValueError("没有可回测的行情数据，请先运行 download 或 analyze。")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    tech = calculate(frame)
    if len(tech) <= config.warmup_bars + 2:
        raise ValueError("行情不足，无法做 walk-forward")
    dates = tech["date"].tolist()
    schedule: dict[str, list[dict]] = {}
    for i in range(
        max(0, config.warmup_bars - 1),
        len(tech) - 1,
        max(1, rebalance_days),
    ):
        train = tech.iloc[max(0, i - train_days + 1): i + 1]
        if len(train) < 30:
            continue
        schedule[dates[min(i + 1, len(dates) - 1)]] = calibrate_zones(train)
    result = run_backtest(
        settings,
        repository,
        config,
        zones_schedule=schedule,
    )
    result["summary"]["walk_forward"] = True
    result["summary"]["data_basis"] = basis
    result["summary"]["train_days"] = train_days
    result["summary"]["rebalance_days"] = rebalance_days
    result["summary"]["rebalances"] = len(schedule)
    result["summary"]["warnings"].extend(
        warnings
        + [
            "walk-forward 使用滚动训练窗口重新校准观察区；交易窗口仍按下一交易日开盘成交。",
            "训练窗口只使用当日及之前的数据，避免观察区参数前视偏差。",
        ]
    )
    return result


def run_backtest(
    settings: Settings,
    repository: Repository,
    config: BacktestConfig | None = None,
    zones_schedule: dict[str, list[dict]] | None = None,
) -> dict:
    config = config or BacktestConfig()
    strategy = deepcopy(settings.strategy)
    raw = repository.adjusted_history(config.code)
    basis = "qfq"
    warnings: list[str] = []
    if raw.empty:
        raw = repository.history(config.code)
        basis = "raw"
        warnings.append("前复权数据不可用，回测使用不复权价格。")
    if raw.empty:
        raise ValueError("没有可回测的行情数据，请先运行 download 或 analyze。")

    frame = raw.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    tech = calculate(frame)
    if len(tech) <= config.warmup_bars + 2:
        raise ValueError(
            f"行情不足：{len(tech)} 根，至少需要 {config.warmup_bars + 3} 根"
        )

    dates = tech["date"].tolist()
    start_candidates = [
        i for i, value in enumerate(dates)
        if i >= config.warmup_bars
        and (config.start is None or value >= config.start)
        and (config.end is None or value <= config.end)
    ]
    if not start_candidates:
        raise ValueError("所选日期区间没有足够的回测数据")
    start_idx = start_candidates[0]
    if start_idx >= len(tech) - 1:
        raise ValueError("回测开始日期太晚，至少需要保留一个下一交易日")
    end_idx = len(tech) - 1
    if config.end is not None:
        end_idx = max(
            i for i, value in enumerate(dates) if value <= config.end and i >= start_idx
        )
    end_idx = min(end_idx, len(tech) - 1)

    first_exec = tech.iloc[start_idx + 1]
    first_price = float(first_exec["open"])
    start_close = float(tech.iloc[start_idx]["close"])
    initial_shares = min(max(0, config.initial_shares), config.max_shares)
    initial_cash = config.initial_cash
    if initial_cash is None:
        initial_cash = 0.0 if initial_shares else (
            config.max_shares * start_close + 2 * config.min_commission
        )
    initial_cash = float(initial_cash)

    cash = initial_cash
    shares = initial_shares
    average_cost = start_close if initial_shares else 0.0
    initial_cost_basis = average_cost
    initial_equity = _equity(shares, cash, start_close)
    realized_pnl = 0.0
    pending: dict | None = None
    cooldown_until = -1
    trades: list[dict] = []
    equity_rows: list[dict] = []
    skipped: list[dict] = []

    # Benchmark: same starting position when initial_shares is set; otherwise
    # buy the maximum position at the first executable open.
    if initial_shares:
        bench_shares, bench_cash = shares, cash
    else:
        bench_shares = 0
        bench_cash = initial_cash
        bench_qty = min(
            config.max_shares,
            int(initial_cash // (first_price * config.lot_size)) * config.lot_size,
        )
        while bench_qty > 0:
            cost = bench_qty * first_price
            fee = _fees(cost, "buy", config)
            if cost + fee <= bench_cash:
                break
            bench_qty -= config.lot_size
        if bench_qty > 0:
            cost = bench_qty * first_price
            fee = _fees(cost, "buy", config)
            bench_cash -= cost + fee
            bench_shares = bench_qty

    for i in range(start_idx, end_idx + 1):
        row = tech.iloc[i]
        close = float(row["close"])

        if pending is not None:
            previous = tech.iloc[i - 1]
            fill = float(row["open"])
            side = "buy" if pending["category"] == "buy" else "sell"
            limit_up = float(previous["close"]) * (1 + config.limit_pct)
            limit_down = float(previous["close"]) * (1 - config.limit_pct)
            blocked = (side == "buy" and fill > limit_up) or (
                side == "sell" and fill < limit_down
            )
            if blocked:
                skipped.append(
                    {
                        "date": str(row["date"]),
                        "side": side,
                        "reason": "涨跌停/无法成交",
                        "signal": pending.get("signal"),
                    }
                )
            elif side == "buy":
                if config.cooldown_days > 0 and i <= cooldown_until:
                    skipped.append(
                        {
                            "date": str(row["date"]),
                            "side": "buy",
                            "reason": "风险卖出后的冷却期",
                            "signal": pending.get("signal"),
                        }
                    )
                else:
                    fill *= 1 + config.slippage_bps / 10000
                    qty = min(pending["shares"], config.max_shares - shares)
                    qty = max(0, qty // config.lot_size * config.lot_size)
                    while qty > 0:
                        amount = qty * fill
                        fee = _fees(amount, "buy", config)
                        if amount + fee <= cash:
                            break
                        qty -= config.lot_size
                    if qty > 0:
                        amount = qty * fill
                        fee = _fees(amount, "buy", config)
                        cash -= amount + fee
                        average_cost = (
                            (average_cost * shares + amount + fee) / (shares + qty)
                        )
                        shares += qty
                        trades.append(
                            {
                                "date": str(row["date"]),
                                "side": "buy",
                                "shares": qty,
                                "price": round(fill, 4),
                                "amount": round(amount, 2),
                                "fee": round(fee, 2),
                                "signal": pending.get("signal"),
                                "reason": pending.get("reason", ""),
                            }
                        )
            else:
                fill *= 1 - config.slippage_bps / 10000
                qty = min(pending["shares"], shares)
                if qty > 0:
                    amount = qty * fill
                    fee = _fees(amount, "sell", config)
                    cash += amount - fee
                    realized_pnl += (fill - average_cost) * qty - fee
                    shares -= qty
                    if shares == 0:
                        average_cost = 0.0
                    trades.append(
                        {
                            "date": str(row["date"]),
                            "side": "sell",
                            "shares": qty,
                            "price": round(fill, 4),
                            "amount": round(amount, 2),
                            "fee": round(fee, 2),
                            "signal": pending.get("signal"),
                            "reason": pending.get("reason", ""),
                        }
                    )
                    if pending.get("signal") in ("RISK_REVIEW", "BREAK_SUPPORT"):
                        cooldown_until = i + config.cooldown_days
            pending = None

        equity_rows.append(
            {
                "date": str(row["date"]),
                "equity": round(_equity(shares, cash, close), 2),
                "benchmark": round(
                    initial_equity if i == start_idx else _equity(bench_shares, bench_cash, close),
                    2,
                ),
                "shares": shares,
                "cash": round(cash, 2),
                "close": round(close, 4),
                "exposure": round(
                    close * shares / max(_equity(shares, cash, close), 1e-9), 4
                ),
            }
        )

        if i >= end_idx:
            break
        if zones_schedule:
            active_zones = _zones_for(str(row["date"]), zones_schedule)
            if active_zones:
                strategy["zones"] = active_zones
        facts = _facts(
            tech.iloc[: i + 1], shares, average_cost, config, settings, strategy
        )
        guide = build_action_guide(
            facts,
            now=datetime.strptime(str(row["date"]), "%Y-%m-%d").replace(tzinfo=TZ),
        )
        pending = guide["actions"][0] if guide["actions"] else None

    equity = pd.Series([item["equity"] for item in equity_rows], dtype="float64")
    benchmark = pd.Series([item["benchmark"] for item in equity_rows], dtype="float64")
    returns = equity.pct_change().dropna()
    bench_returns = benchmark.pct_change().dropna()
    final_equity = float(equity.iloc[-1])
    total_return = final_equity / initial_equity - 1
    bench_return = float(benchmark.iloc[-1]) / initial_equity - 1
    drawdown = (equity / equity.cummax() - 1).min()
    bench_drawdown = (benchmark / benchmark.cummax() - 1).min()
    days = max(len(returns), 1)
    cagr = (final_equity / initial_equity) ** (252 / days) - 1
    volatility = float(returns.std() * sqrt(252)) if len(returns) > 1 else 0.0
    sharpe = (
        float(returns.mean() / returns.std() * sqrt(252))
        if len(returns) > 1 and returns.std() > 0
        else None
    )
    bench_volatility = (
        float(bench_returns.std() * sqrt(252)) if len(bench_returns) > 1 else 0.0
    )
    bench_sharpe = (
        float(bench_returns.mean() / bench_returns.std() * sqrt(252))
        if len(bench_returns) > 1 and bench_returns.std() > 0
        else None
    )
    turnover = (
        sum(abs(trade["amount"]) for trade in trades) / max(equity.mean(), 1e-9)
    )

    # Pair each sell with the preceding buy average for trade-level win rate.
    # Starting shares are treated as an entry at the starting close.
    entry_cost = initial_cost_basis * initial_shares
    entry_shares = initial_shares
    for trade in trades:
        if trade["side"] == "buy":
            entry_shares += trade["shares"]
            entry_cost += trade["amount"] + trade["fee"]
        elif entry_shares:
            avg = entry_cost / entry_shares
            trade["pnl"] = round(
                (trade["price"] - avg) * trade["shares"] - trade["fee"], 2
            )
            take = min(entry_shares, trade["shares"])
            entry_shares -= take
            entry_cost -= avg * take
    sells = [trade for trade in trades if trade["side"] == "sell"]
    wins = sum(1 for trade in sells if trade.get("pnl", 0) > 0)
    average_exposure = sum(
        item["exposure"] for item in equity_rows
    ) / len(equity_rows)

    summary = {
        "code": config.code,
        "data_basis": basis,
        "start": equity_rows[0]["date"],
        "end": equity_rows[-1]["date"],
        "bars": len(equity_rows),
        "initial_cash": round(initial_cash, 2),
        "initial_shares": initial_shares,
        "initial_equity": round(initial_equity, 2),
        "final_equity": round(final_equity, 2),
        "final_cash": round(cash, 2),
        "final_shares": shares,
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(drawdown * 100, 2),
        "volatility_pct": round(volatility * 100, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "benchmark_return_pct": round(bench_return * 100, 2),
        "benchmark_max_drawdown_pct": round(bench_drawdown * 100, 2),
        "benchmark_volatility_pct": round(bench_volatility * 100, 2),
        "benchmark_sharpe": round(bench_sharpe, 2) if bench_sharpe is not None else None,
        "excess_return_pct": round((total_return - bench_return) * 100, 2),
        "trades": len(trades),
        "sells": len(sells),
        "win_rate_pct": round(wins / len(sells) * 100, 2) if sells else None,
        "realized_pnl": round(realized_pnl, 2),
        "turnover": round(turnover, 2),
        "average_exposure": round(average_exposure, 2),
        "walk_forward": bool(zones_schedule),
        "rebalances": len(zones_schedule or {}),
        "config": {**asdict(config), "initial_cash": initial_cash},
        "warnings": warnings
        + [
            "回测只用价格/技术/当前观察区，不包含历史新闻、公告、财务和估值。",
            "回测使用下一交易日开盘成交，含手续费、印花税、滑点和 100 股整数倍限制。",
            (
                "观察区由滚动训练窗口校准，交易窗口不使用未来数据。"
                if zones_schedule
                else "观察区使用 2026-10-20 校准的当前配置，回测区间早于校准日，存在策略配置前视偏差；正式结论应做 walk-forward。"
            ),
            f"策略平均仓位约 {average_exposure * 100:.1f}%，与满仓买入持有基准的收益/回撤不能直接类比。",
        ],
    }

    return {
        "summary": summary,
        "equity": equity_rows,
        "trades": trades,
        "skipped": skipped,
    }


def save_backtest(result: dict, root: Path, tag: str = "") -> tuple[Path, Path]:
    folder = root / "reports/backtest"
    folder.mkdir(parents=True, exist_ok=True)
    summary = result["summary"]
    stem = (
        f"{summary['code'].replace('.', '_')}_"
        f"{summary['start']}_{summary['end']}_"
        f"init{summary['config'].get('initial_shares', 0)}"
        + (f"_{tag}" if tag else "")
    )
    json_path = folder / f"{stem}.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    lines = [
        f"# 回测报告 · {summary['code']}",
        "",
        f"- 区间：{summary['start']} 至 {summary['end']}（{summary['bars']} 个交易日）",
        f"- 数据口径：{'前复权' if summary['data_basis'] == 'qfq' else '不复权'}",
        f"- 初始权益：{summary['initial_equity']:,.2f} 元（现金 {summary['initial_cash']:,.2f} 元）",
        f"- 期末权益：{summary['final_equity']:,.2f} 元",
        f"- 累计收益：{summary['total_return_pct']:+.2f}%",
        f"- 年化收益：{summary['cagr_pct']:+.2f}%",
        f"- 最大回撤：{summary['max_drawdown_pct']:.2f}%",
        f"- 基准（买入持有）：{summary['benchmark_return_pct']:+.2f}%（最大回撤 {summary['benchmark_max_drawdown_pct']:.2f}%，夏普 {summary['benchmark_sharpe'] if summary['benchmark_sharpe'] is not None else '—'}）",
        f"- 超额收益：{summary['excess_return_pct']:+.2f}%",
        f"- 夏普：{summary['sharpe'] if summary['sharpe'] is not None else '—'}",
        f"- 交易次数：{summary['trades']}；卖出次数：{summary['sells']}；胜率：{summary['win_rate_pct'] if summary['win_rate_pct'] is not None else '—'}%",
        f"- 平均仓位：{summary['average_exposure'] * 100:.1f}%",
        "",
        "## 配置",
        "",
        "```json",
        json.dumps(summary["config"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## 最近交易",
        "",
        "| 日期 | 方向 | 股数 | 价格 | 金额 | 费用 | 信号 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for trade in result["trades"][-30:]:
        lines.append(
            f"| {trade['date']} | {trade['side']} | {trade['shares']} | "
            f"{trade['price']} | {trade['amount']} | {trade['fee']} | "
            f"{trade.get('signal') or ''} |"
        )
    lines.extend(["", "## 说明", ""])
    lines.extend(f"- {item}" for item in summary["warnings"])
    md_path = folder / f"{stem}.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path
