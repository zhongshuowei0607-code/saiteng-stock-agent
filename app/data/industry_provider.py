from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
from app.database.repository import Repository, clean
from .bounded import fetch
from .market_provider import validate, date_range


def comparison(
    frames: dict[str, pd.DataFrame], names: dict[str, str], target: str
) -> dict:
    if target not in frames or frames[target].empty:
        return {"rows": [], "relative": "数据不足，无法判断。"}
    date = frames[target].iloc[-1]["date"]
    rows = []
    excluded = []
    for code, frame in frames.items():
        df = frame[frame.date <= date].sort_values("date")
        if len(df) < 21 or df.iloc[-1]["date"] != date:
            excluded.append(code)
            continue
        last = df.iloc[-1]
        rows.append(
            {
                "code": code,
                "name": names[code],
                "date": date,
                "pct_change": last["pct_change"],
                "return5": (last.close / df.close.iloc[-6] - 1) * 100,
                "return20": (last.close / df.close.iloc[-21] - 1) * 100,
                "amount_change": (last.amount / df.amount.iloc[-6:-1].mean() - 1) * 100
                if df.amount.iloc[-6:-1].mean() > 0
                else None,
                "turnover": last.get("turnover"),
                "pe": last.get("pe"),
                "pb": last.get("pb"),
            }
        )
    if len(rows) < 2 or target not in [r["code"] for r in rows]:
        return {
            "rows": clean(rows),
            "relative": "数据不足，无法判断。",
            "excluded": excluded,
        }
    table = pd.DataFrame(rows)
    table["daily_rank"] = (
        table["pct_change"].rank(ascending=False, method="min").astype(int)
    )
    table["strength_rank"] = table.return20.rank(ascending=False, method="min").astype(
        int
    )
    own = table[table.code == target].iloc[0]
    avg = table[table.code != target]["pct_change"].mean()
    difference = own["pct_change"] - avg
    return {
        "rows": clean(table.sort_values("daily_rank").to_dict("records")),
        "relative": "个股强于行业"
        if difference > 1
        else "个股弱于行业"
        if difference < -1
        else "基本同步",
        "difference_pp": float(difference),
        "excluded": excluded,
        "note": "用户候选同行池，非完整行业指数；强弱排名按20日涨幅。",
    }


class IndustryProvider:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    def fetch(self, code: str, names: dict[str, str], own: pd.DataFrame) -> dict:
        frames = {code: own}
        errors = []

        def download(peer: str) -> tuple[str, pd.DataFrame]:
            start, end = date_range(80)
            for source in ("tushare_history", "akshare_history"):
                try:
                    return peer, validate(
                        fetch(source, {"code": peer, "start": start, "end": end})
                    )
                except Exception:
                    continue
            return peer, self.repository.history(peer)

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(download, peer) for peer in names if peer != code]
            for job in as_completed(jobs):
                peer, frame = job.result()
                if frame.empty:
                    errors.append(peer + "同行行情缺失")
                else:
                    self.repository.save_bars(peer, frame)
                    frames[peer] = frame
        return {**comparison(frames, names, code), "errors": errors}
