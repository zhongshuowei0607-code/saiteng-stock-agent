import pandas as pd
from .market_provider import MarketDataProvider, normalize_code


class AKShareProvider(MarketDataProvider):
    def history(self, code: str, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        frame = ak.stock_zh_a_hist(
            symbol=normalize_code(code)[:6],
            period="daily",
            start_date=start,
            end_date=end,
            adjust="",
            timeout=20,
        )
        frame = frame.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover",
                "涨跌幅": "pct_change",
                "涨跌额": "change",
            }
        )
        if not frame.empty:
            frame["pre_close"] = frame["close"] - frame["change"]
            frame["source"] = "AKShare / 东方财富（不复权）"
        return frame
