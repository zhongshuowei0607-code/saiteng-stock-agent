import pandas as pd

def stabilization(df: pd.DataFrame) -> dict:
    if len(df) < 30:
        return {"score":None,"max_score":10,"level":None,"signals":[],"note":"数据不足，无法判断。"}
    a,b,c = df.iloc[-1],df.iloc[-2],df.iloc[-3]
    span = a.high-a.low
    body = abs(a.close-a.open)
    prior_window = df.iloc[-21:-1]
    low_index = prior_window.low.idxmin()
    prior_low = df.loc[low_index]
    checks = [
        (a.low >= prior_window.low.min(),"未创近20日新低"),
        (span > 0 and min(a.open,a.close)-a.low >= max(body,span*.25),"明显下影线"),
        (span > 0 and a.close >= (a.high+a.low)/2,"收盘位于当日上半区"),
        (a.RSI14 > b.RSI14,"RSI14回升"),
        (a.MACD > b.MACD,"MACD柱改善"),
        (a.close > a.MA5 and b.close <= b.MA5,"重新站上MA5"),
        (a.volume < b.VOL_MA5,"成交量低于此前五日均量"),
        (a.low > b.low > c.low,"连续两日低点抬高"),
        (b.close < b.open and a.close > a.open and a.open <= b.close and a.close >= b.open,"阳包阴"),
        (a.low < prior_low.low and a.DIF > prior_low.DIF and a.DIF < 0,"价格新低但DIF较前低改善（背离候选）")]
    signals = [{"name":name,"confirmed":bool(value)} for value,name in checks]
    score = sum(x["confirmed"] for x in signals)
    return {"score":score,"max_score":10,"level":"HIGH" if score>=7 else "MEDIUM" if score>=4 else "LOW","signals":signals,"note":"规则评分并非反转概率；背离仅为候选特征。"}
