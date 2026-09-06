def compare(previous: dict | None, current: dict) -> dict:
    if previous is None:
        return {"note": "尚无前一交易日观点，无法比较。"}
    changes = []
    a, b = previous.get("technical", {}), current.get("technical", {})
    if all(
        x is not None
        for x in (a.get("close"), a.get("MA20"), b.get("close"), b.get("MA20"))
    ):
        if a["close"] >= a["MA20"] and b["close"] < b["MA20"]:
            changes.append("跌破 MA20")
        if a["close"] <= a["MA20"] and b["close"] > b["MA20"]:
            changes.append("重新站上 MA20")
    if a.get("volume_signal") != b.get("volume_signal"):
        changes.append(f"量价信号：{a.get('volume_signal')} → {b.get('volume_signal')}")

    def rank(report: dict) -> int | None:
        return next(
            (
                r.get("daily_rank")
                for r in report.get("industry", {}).get("rows", [])
                if r["code"] == report["stock"]["code"]
            ),
            None,
        )

    old, new = rank(previous), rank(current)
    old_pool = {r["code"] for r in previous.get("industry", {}).get("rows", [])}
    new_pool = {r["code"] for r in current.get("industry", {}).get("rows", [])}
    if old is not None and new is not None and old_pool == new_pool and old != new:
        changes.append("行业涨幅排名" + ("下降" if new > old else "上升"))
    if previous["risk"].get("coverage") != current["risk"].get("coverage"):
        changes.append("风险数据覆盖率变化，分值不完全可比")
    return {
        "previous_date": previous["date"],
        "previous_market_date": previous.get("market", {}).get("date"),
        "risk": {"from": previous["risk"]["score"], "to": current["risk"]["score"]},
        "trend": {"from": previous["trend"], "to": current["trend"]},
        "state": {
            "from": previous["watch_zone"]["state"],
            "to": current["watch_zone"]["state"],
        },
        "changes": changes or ["未检测到可归因的规则变化"],
    }
