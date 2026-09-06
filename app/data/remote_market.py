import os
import pandas as pd
from .bounded import fetch
from .market_provider import MarketDataProvider


class RemoteMarketProvider(MarketDataProvider):
    def __init__(self, source: str) -> None:
        self.source = source

    def history(self, code: str, start: str, end: str) -> pd.DataFrame:
        if self.source == "tushare_history" and not os.getenv("TUSHARE_TOKEN"):
            raise ValueError("未配置 TUSHARE_TOKEN")
        return fetch(
            self.source, {"code": code, "start": start, "end": end}, timeout=40
        )


def providers() -> list[MarketDataProvider]:
    return [
        RemoteMarketProvider("tushare_history"),
        RemoteMarketProvider("akshare_history"),
    ]
