import logging
import os

import pandas as pd
from .market_provider import MarketDataProvider, normalize_code


class AKShareProvider(MarketDataProvider):
    def history(self, code: str, start: str, end: str) -> pd.DataFrame:
        # macOS can expose a system proxy to Requests without shell proxy
        # variables. Eastmoney often closes proxied requests, so bypass the
        # proxy only for its public market-data hosts inside this worker.
        bypass = ".eastmoney.com,push2his.eastmoney.com"
        for key in ("NO_PROXY", "no_proxy"):
            current = os.getenv(key, "")
            os.environ[key] = ",".join(item for item in (current, bypass) if item)
        import akshare as ak

        normalized = normalize_code(code)
        try:
            frame = ak.stock_zh_a_hist(
                symbol=normalized[:6],
                period="daily",
                start_date=start,
                end_date=end,
                adjust="",
                timeout=20,
            )
        except Exception as exc:
            logging.warning("东方财富行情不可用，切换新浪行情：%s", type(exc).__name__)
            prefix = normalized[-2:].lower()
            frame = ak.stock_zh_a_daily(
                symbol=f"{prefix}{normalized[:6]}",
                start_date=start,
                end_date=end,
                adjust="",
            )
            if not frame.empty:
                # 新浪成交量单位为股、换手率为小数；统一为手和百分比。
                frame["volume"] = frame["volume"] / 100
                frame["turnover"] = frame["turnover"] * 100
                frame["pre_close"] = frame["close"].shift(1)
                frame["change"] = frame["close"].diff()
                frame["pct_change"] = frame["close"].pct_change() * 100
                frame["source"] = "AKShare / 新浪财经（不复权）"
            return frame
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
