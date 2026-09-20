"""A single-symbol quote with the source timestamp (never a daily-bar proxy)."""

from datetime import datetime
import re
from zoneinfo import ZoneInfo
import httpx

from app.analysis.action_plan import number
from .market_provider import normalize_code


def parse_tencent_quote(text: str, code: str = "603283.SH") -> dict:
    code = normalize_code(code)
    symbol = code[-2:].lower() + code[:6]
    match = re.search(r'v_' + re.escape(symbol) + r'="([^"]*)"', text)
    parts = match.group(1).split("~") if match else []
    if len(parts) < 39 or parts[2] != code[:6]:
        raise ValueError("实时报价格式或股票代码不匹配")
    price, previous = number(parts[3]), number(parts[4])
    if price is None or price <= 0 or previous is None or previous <= 0:
        raise ValueError("实时报价价格无效")
    moment = datetime.strptime(parts[30], "%Y%m%d%H%M%S").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return {
        "date": moment.date().isoformat(), "quote_time": moment.isoformat(),
        "is_realtime": True, "close": price, "pre_close": previous,
        "pct_change": (price / previous - 1) * 100,
        "open": number(parts[5]), "high": number(parts[33]), "low": number(parts[34]),
        "volume": number(parts[6]),
        "amount": (number(parts[38]) * 10000) if number(parts[38]) is not None else None,
        "source": "腾讯财经实时报价", "code": code,
    }


def fetch_realtime_quote(code: str = "603283.SH") -> dict:
    code = normalize_code(code)
    symbol = code[-2:].lower() + code[:6]
    with httpx.Client(timeout=httpx.Timeout(8, connect=3)) as client:
        response = client.get("https://qt.gtimg.cn/q=" + symbol)
        response.raise_for_status()
        return parse_tencent_quote(response.content.decode("gb18030", errors="replace"), code)
