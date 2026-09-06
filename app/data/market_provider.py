from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging
import re
import pandas as pd
FIELDS = ["date", "open", "close", "high", "low", "pre_close", "change", "pct_change", "volume", "amount", "turnover", "pe", "pb", "total_mv", "circ_mv"]

def normalize_code(code: str) -> str:
    value = code.strip().upper()
    match = re.fullmatch(r"(?:(SH|SZ|BJ))?(\d{6})(?:\.(SH|SZ|BJ))?", value)
    if not match:
        raise ValueError("股票代码格式错误")
    prefix, number, suffix = match.groups()
    exchange = "SH" if number[0] in "69" else "BJ" if number[0] in "48" else "SZ"
    if any(x and x != exchange for x in (prefix, suffix)):
        raise ValueError("股票代码与交易所不匹配")
    return f"{number}.{exchange}"

def date_range(days: int = 800) -> tuple[str, str]:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    # 收盘前不纳入可能尚未完成的当日 K 线。
    end = now.date() if now.hour >= 15 else now.date() - timedelta(days=1)
    return (end - timedelta(days=days)).strftime("%Y%m%d"), end.strftime("%Y%m%d")

def validate(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        raise ValueError("行情为空")
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    for key in FIELDS[1:]:
        frame[key] = pd.to_numeric(frame[key], errors="coerce") if key in frame else float("nan")
    required = frame[["open", "close", "high", "low", "volume", "amount"]]
    if required.isna().any().any() or (frame[["open", "close", "high", "low"]] <= 0).any().any():
        raise ValueError("行情含无效价格或成交数据")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) | (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("OHLC 关系无效")
    return frame.reset_index(drop=True)

class MarketDataProvider(ABC):
    @abstractmethod
    def history(self, code: str, start: str, end: str) -> pd.DataFrame: ...

class MarketService:
    def __init__(self, providers: list[MarketDataProvider], repository):
        self.providers, self.repository = providers, repository
    def update(self, code: str, days: int = 800) -> tuple[pd.DataFrame, list[str]]:
        errors = []
        for provider in self.providers:
            try:
                frame = validate(provider.history(code, *date_range(days)))
                self.repository.save_bars(code, frame)
                return frame, errors
            except Exception as exc:
                message = f"{type(provider).__name__} 获取失败：{type(exc).__name__}"
                logging.warning(message)
                errors.append(message)
        cached = self.repository.history(code)
        errors.append("全部行情源失败；使用缓存（如有），请核对行情日期。")
        return cached, errors
