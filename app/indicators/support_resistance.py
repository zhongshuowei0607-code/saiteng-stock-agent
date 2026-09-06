import numpy as np
import pandas as pd

def levels(df: pd.DataFrame) -> dict:
    if len(df) < 20:
        return {"support":[],"resistance":[],"note":"数据不足，无法判断。"}
    row = df.iloc[-1]; price = float(row.close)
    atr = float(row.ATR) if pd.notna(row.get("ATR")) else price*.02
    tolerance = max(atr*.35, price*.003)
    candidates: list[tuple[float,str]] = []
    for n in (20,60,120):
        if len(df) >= n:
            candidates.extend([(float(df.low.tail(n).min()),f"{n}日低点"),(float(df.high.tail(n).max()),f"{n}日高点")])
    for key in ("MA20","MA60"):
        if pd.notna(row.get(key)):
            candidates.append((float(row[key]),key))
    prior = df.iloc[-2]
    pivot = (prior.high+prior.low+prior.close)/3
    candidates.extend([(float(pivot),"昨日Pivot"),(float(2*pivot-prior.high),"Pivot S1"),(float(2*pivot-prior.low),"Pivot R1")])
    recent = df.tail(120)
    typical = (recent.high+recent.low+recent.close)/3
    histogram, bins = np.histogram(typical, bins=16, weights=recent.volume)
    for i in histogram.argsort()[-3:]:
        candidates.append((float((bins[i]+bins[i+1])/2),"日线成交密集区估计"))
    for i in range(max(2,len(df)-60),len(df)-2):
        if df.low.iloc[i] == df.low.iloc[i-2:i+3].min():
            candidates.append((float(df.low.iloc[i]),"局部低点"))
        if df.high.iloc[i] == df.high.iloc[i-2:i+3].max():
            candidates.append((float(df.high.iloc[i]),"局部高点"))
    groups: list[list[tuple[float,str]]] = []
    for candidate in sorted(candidates):
        if groups and candidate[0]-np.mean([x[0] for x in groups[-1]]) <= tolerance:
            groups[-1].append(candidate)
        else:
            groups.append([candidate])
    output = {"support":[],"resistance":[],"note":"启发式参考；成交密集区由日线估计，非逐笔成交分布。"}
    for group in groups:
        value = round(float(np.mean([x[0] for x in group])),2)
        reasons = sorted(set(x[1] for x in group))
        item = {"price":value,"strength":round(min(.95,.25+.13*len(reasons)),2),"reason":" + ".join(reasons)}
        if value != price:
            output["support" if value < price else "resistance"].append(item)
    output["support"] = sorted(output["support"],key=lambda x:-x["price"])[:3]
    output["resistance"] = sorted(output["resistance"],key=lambda x:x["price"])[:3]
    return output
