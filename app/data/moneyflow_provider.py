import os
import pandas as pd
from .bounded import fetch


def _tushare_flow(code: str, market_date: str) -> dict | None:
    if not os.getenv("TUSHARE_TOKEN"):
        return None
    frame = fetch("tushare_moneyflow", {"ts_code": code, "trade_date": market_date.replace("-", "")})
    if frame.empty:
        return None
    frame = frame[frame.trade_date.astype(str) == market_date.replace("-", "")]
    if frame.empty:
        return None
    value = frame.iloc[-1].get("net_mf_amount")
    return {
        "date": market_date,
        "net_amount": None if value is None else float(value) * 10000,
        "source": "Tushare moneyflow",
        "unit": "元",
        "note": "主动买卖净额，不等同所有买卖金额之差。",
    }


def _eastmoney_flow(code: str, market_date: str) -> dict | None:
    market = code[-2:].lower()
    frame = fetch(
        "stock_individual_fund_flow",
        {"stock": code[:6], "market": market},
        timeout=25,
    )
    if frame.empty or "日期" not in frame:
        return None
    dates = pd.to_datetime(frame["日期"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame = frame[dates == market_date]
    if frame.empty:
        return None
    row = frame.iloc[-1]
    value = row.get("主力净流入-净额")
    if value is None or pd.isna(value):
        return None
    return {
        "date": market_date,
        "net_amount": float(value),
        "source": "东方财富个股资金流",
        "unit": "元",
        "note": "主力资金净额，不等同所有买卖金额之差。",
    }


def moneyflow(code: str, market_date: str) -> dict:
    errors = []
    try:
        value = _tushare_flow(code, market_date)
        if value:
            return value
    except Exception as exc:
        errors.append("Tushare：" + type(exc).__name__)
    try:
        value = _eastmoney_flow(code, market_date)
        if value:
            return value
    except Exception as exc:
        errors.append("东方财富：" + type(exc).__name__)
    note = "数据不足，无法判断。资金流可能尚未发布。"
    if errors:
        note += " " + "；".join(errors)
    return {"note": note}
