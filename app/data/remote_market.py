import os
import pandas as pd
from .bounded import fetch
from .market_provider import MarketDataProvider


class RemoteMarketProvider(MarketDataProvider):
    def __init__(self, source: str, adjust: str = "") -> None:
        self.source, self.adjust = source, adjust

    def history(
        self, code: str, start: str, end: str, adjust: str = ""
    ) -> pd.DataFrame:
        if self.source == "tushare_history" and not os.getenv("TUSHARE_TOKEN"):
            raise ValueError("未配置 TUSHARE_TOKEN")
        args = {"code": code, "start": start, "end": end}
        selected = adjust or self.adjust
        if selected:
            args["adjust"] = selected
        return fetch(self.source, args, timeout=40)


def providers() -> list[MarketDataProvider]:
    return [
        RemoteMarketProvider("tushare_history"),
        RemoteMarketProvider("akshare_history"),
    ]


def adjusted_providers() -> list[MarketDataProvider]:
    """Prefer AKShare for qfq: the Tushare daily token has been unreliable."""
    return [
        RemoteMarketProvider("akshare_history", "qfq"),
        RemoteMarketProvider("tushare_history", "qfq"),
    ]
