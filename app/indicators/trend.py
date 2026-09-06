import pandas as pd


def trends(df: pd.DataFrame) -> dict:
    result = {}
    for name, fast, slow, window in (
        ("short", 5, 20, 10),
        ("medium", 20, 60, 20),
        ("long", 60, 250, 60),
    ):
        if len(df) < slow + 5:
            result[name] = {"state": None, "reason": "数据不足，无法判断。"}
            continue
        row, previous = df.iloc[-1], df.iloc[-6]
        score = 0
        reasons = []
        for condition, reason in [
            (row.close > row[f"MA{fast}"], f"价格与MA{fast}"),
            (row[f"MA{fast}"] > row[f"MA{slow}"], "均线排列"),
            (row[f"MA{slow}"] > previous[f"MA{slow}"], "均线斜率"),
            (row.MACD > 0, "MACD"),
            (row.RSI14 > 50, "RSI"),
        ]:
            score += 1 if condition else -1
            reasons.append(reason + ("偏强" if condition else "偏弱"))
        older, newer = df.iloc[-2 * window : -window], df.tail(window)
        structure = (
            newer.low.min() > older.low.min() and newer.high.max() > older.high.max()
        )
        falling = (
            newer.low.min() < older.low.min() and newer.high.max() < older.high.max()
        )
        score += int(structure) - int(falling)
        if row.volume_signal in ("放量上涨", "放量下跌"):
            score += 1 if row.volume_signal == "放量上涨" else -1
        state = (
            "STRONG_BULL"
            if score >= 5
            else "BULL"
            if score >= 2
            else "STRONG_BEAR"
            if score <= -5
            else "BEAR"
            if score <= -2
            else "SIDEWAYS"
        )
        result[name] = {
            "state": state,
            "score": score,
            "reasons": reasons
            + [
                str(row.volume_signal),
                "高低点抬高"
                if structure
                else "高低点降低"
                if falling
                else "高低点结构未确认",
            ],
        }
    return result
