from .bounded import fetch


def moneyflow(code: str, market_date: str) -> dict:
    frame = fetch(
        "tushare_moneyflow",
        {"ts_code": code, "trade_date": market_date.replace("-", "")},
    )
    if frame.empty:
        return {"note": "数据不足，无法判断。资金流可能尚未发布。"}
    frame = frame[frame.trade_date.astype(str) == market_date.replace("-", "")]
    if frame.empty:
        return {"note": "资金流日期不匹配，数据不足，无法判断。"}
    value = frame.iloc[-1].get("net_mf_amount")
    return {
        "date": market_date,
        "net_amount": None if value is None else float(value) * 10000,
        "source": "Tushare moneyflow",
        "unit": "元",
        "note": "主动买卖净额，不等同所有买卖金额之差。",
    }
