import numpy as np
import pandas as pd

def rsi(close: pd.Series, period: int) -> pd.Series:
    """Wilder 平滑；横盘为 50，只有上涨为 100，暖机期保留 NaN。"""
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), period)
    loss = wilder(-delta.clip(upper=0), period)
    result = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    return result.mask((loss == 0) & (gain > 0), 100).mask((gain == 0) & (loss > 0), 0).mask((gain == 0) & (loss == 0), 50)

def wilder(series: pd.Series, period: int) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    first = series.first_valid_index()
    if first is None:
        return out
    start = series.index.get_loc(first) + period - 1
    if start >= len(series):
        return out
    out.iloc[start] = series.iloc[start-period+1:start+1].mean()
    for i in range(start+1, len(series)):
        out.iloc[i] = (out.iloc[i-1] * (period-1) + series.iloc[i]) / period
    return out

def calculate(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    df = frame.sort_values("date").reset_index(drop=True).copy()
    close, high, low = df.close, df.high, df.low
    for n in (5,10,20,60,120,250):
        df[f"MA{n}"] = close.rolling(n).mean()
    df["DIF"] = close.ewm(span=12,adjust=False).mean() - close.ewm(span=26,adjust=False).mean()
    df["DEA"] = df.DIF.ewm(span=9,adjust=False).mean()
    df["MACD"] = 2 * (df.DIF - df.DEA)
    for n in (6,12,14,24):
        df[f"RSI{n}"] = rsi(close,n)
    lo9, hi9 = low.rolling(9).min(), high.rolling(9).max()
    rsv = (100 * (close-lo9) / (hi9-lo9).replace(0,np.nan)).mask(hi9 == lo9,50)
    df["K"] = rsv.ewm(alpha=1/3,adjust=False).mean()
    df["D"] = df.K.ewm(alpha=1/3,adjust=False).mean()
    df["J"] = 3*df.K-2*df.D
    tr = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    df["ATR"] = wilder(tr,14)
    df["BOLL_MID"] = df.MA20
    df["BOLL_UPPER"] = df.MA20 + 2*close.rolling(20).std(ddof=0)
    df["BOLL_LOWER"] = df.MA20 - 2*close.rolling(20).std(ddof=0)
    df["ROC"] = close.pct_change(12,fill_method=None)*100
    df["Momentum"] = close-close.shift(10)
    for n in (5,10,20):
        df[f"VOL_MA{n}"] = df.volume.rolling(n).mean()
    for n in (20,60,120):
        df[f"HIGH{n}"] = high.rolling(n).max()
        df[f"LOW{n}"] = low.rolling(n).min()
    # 相对昨日已完成的五日均量，避免当日巨量抬高比较基准。
    ratio = df.volume / df.VOL_MA5.shift().replace(0,np.nan)
    df["volume_ratio"] = ratio
    rising = close > df.pre_close
    df["volume_signal"] = np.select([ratio.ge(1.2)&rising,ratio.ge(1.2)&~rising,ratio.le(.8)&rising,ratio.le(.8)&~rising], ["放量上涨","放量下跌","缩量上涨","缩量下跌"], default="量价变化不显著")
    return df
