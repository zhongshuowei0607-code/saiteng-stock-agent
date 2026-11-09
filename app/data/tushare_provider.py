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

    def history(
        self, code: str, start: str, end: str, adjust: str = ""
    ) -> pd.DataFrame:
        pro = self.client()
        args = dict(ts_code=normalize_code(code), start_date=start, end_date=end)
        if adjust:
            import tushare as ts

            frame = ts.pro_bar(
                ts_code=args["ts_code"],
                adj=adjust,
                start_date=start,
                end_date=end,
            )
            if frame is None or frame.empty:
                return pd.DataFrame()
        else:
            frame = pro.daily(**args)
            if frame.empty:
                return frame
            try:
                basic = pro.daily_basic(
                    **args,
                    fields="ts_code,trade_date,turnover_rate,pe,pb,total_mv,circ_mv",
                )
                frame = frame.merge(
                    basic, on=["ts_code", "trade_date"], how="left"
                )
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
        if "pre_close" not in frame:
            frame["pre_close"] = frame["close"].shift(1)
        if "change" not in frame:
            frame["change"] = frame["close"] - frame["pre_close"]
        if "pct_change" not in frame:
            frame["pct_change"] = (
                frame["close"] / frame["pre_close"] - 1
            ) * 100
        if "amount" in frame:
            frame["amount"] *= 1000  # 千元转元；成交量统一为手。
        for key in ("total_mv", "circ_mv"):
            if key in frame:
                frame[key] *= 10000
        frame["source"] = (
            f"Tushare {adjust}（前复权）" if adjust else "Tushare daily（不复权）"
        )
        return frame
