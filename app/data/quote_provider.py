import requests
import pandas as pd
import time

from .market_provider import normalize_code


def _number(value: object) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_quote(code: str, market_date: str) -> pd.DataFrame:
    normalized = normalize_code(code)
    session = requests.Session()
    session.trust_env = False
    response = None
    for attempt in range(3):
        try:
            response = session.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params={
                    "sortColumns": "TRADE_DATE",
                    "sortTypes": "-1",
                    "pageSize": "30",
                    "pageNumber": "1",
                    "reportName": "RPT_VALUEANALYSIS_DET",
                    "columns": "ALL",
                    "source": "WEB",
                    "client": "WEB",
                    "filter": f'(SECURITY_CODE="{normalized[:6]}")',
                },
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://data.eastmoney.com/",
                },
                timeout=12,
            )
            response.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(0.4 * (attempt + 1))
    if response is None:
        raise RuntimeError("行情估值快照未返回结果")
    rows = ((response.json() or {}).get("result") or {}).get("data") or []
    data = next(
        (
            row
            for row in rows
            if str(row.get("TRADE_DATE", "")).startswith(market_date)
        ),
        None,
    )
    if data is None:
        return pd.DataFrame()
    row = {
        "code": normalized,
        "date": market_date,
        "close": _number(data.get("CLOSE_PRICE")),
        "pe": _number(data.get("PE_TTM")),
        "pb": _number(data.get("PB_MRQ")),
        "total_mv": _number(data.get("TOTAL_MARKET_CAP")),
        "circ_mv": _number(data.get("NOTLIMITED_MARKETCAP_A")),
        "source": "东方财富估值分析",
    }
    return pd.DataFrame([row])
