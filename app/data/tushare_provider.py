import os
from typing import Any
import logging
import pandas as pd
from .market_provider import MarketDataProvider, normalize_code


class TushareProvider(MarketDataProvider):
    def client(self) -> Any:
        import tushare as ts

        token = os.getenv("TUSHARE_TOKEN")
        if not token:
            raise ValueError("未配置 TUSHARE_TOKEN")
        return ts.pro_api(token, timeout=20)

    def history(self, code: str, start: str, end: str) -> pd.DataFrame:
        pro = self.client()
        args = dict(ts_code=normalize_code(code), start_date=start, end_date=end)
        frame = pro.daily(**args)
        if frame.empty:
            return frame
        try:
            basic = pro.daily_basic(
                **args, fields="ts_code,trade_date,turnover_rate,pe,pb,total_mv,circ_mv"
            )
            frame = frame.merge(basic, on=["ts_code", "trade_date"], how="left")
        except Exception:
            logging.warning("Tushare 估值/换手率不可用，保留缺失值")
        frame = frame.rename(
            columns={
                "trade_date": "date",
                "pct_chg": "pct_change",
                "vol": "volume",
                "turnover_rate": "turnover",
            }
        )
        frame["amount"] *= 1000  # 千元转元；成交量统一为手。
        for key in ("total_mv", "circ_mv"):
            if key in frame:
                frame[key] *= 10000
        frame["source"] = "Tushare daily（不复权）"
        return frame
