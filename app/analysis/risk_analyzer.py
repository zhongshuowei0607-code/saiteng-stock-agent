import math


def risk_score(facts: dict) -> dict:
    market, technical = facts.get("market"), facts.get("technical", {})
    if not market:
        return {
            "score": None,
            "level": None,
            "stars": "—",
            "reasons": ["数据不足，无法判断。"],
            "missing": ["行情"],
        }
    components: list[dict] = []
    missing = []

    def add(name: str, value: float | None, weight: int, reason: str) -> None:
        if value is None:
            missing.append(name)
        else:
            components.append(
                {
                    "name": name,
                    "value": min(100, max(0, value)),
                    "weight": weight,
                    "reason": reason,
                }
            )

    trend = facts.get("trend", {}).get("medium", {}).get("state")
    add(
        "趋势",
        {
            "STRONG_BULL": 15,
            "BULL": 30,
            "SIDEWAYS": 50,
            "BEAR": 75,
            "STRONG_BEAR": 95,
        }.get(trend),
        20,
        str(trend),
    )
    atr = technical.get("ATR")
    add(
        "波动",
        atr / market["close"] * 2000 if atr is not None else None,
        10,
        "ATR/价格",
    )
    pct = market.get("pct_change")
    add("跌幅", max(0, -pct) * 12 if pct is not None else None, 10, "当日跌幅")
    add(
        "成交量",
        85 if technical.get("volume_signal") == "放量下跌" else 35,
        8,
        str(technical.get("volume_signal")),
    )
    pe = market.get("pe")
    add(
        "估值",
        min(100, pe) if pe is not None and pe > 0 else None,
        8,
        "PE启发式阈值，非行业公允估值",
    )
    pnl = facts.get("portfolio", {}).get("pnl_pct")
    add(
        "成本距离", max(0, -pnl) * 4 if pnl is not None else None, 8, "相对持仓成本浮亏"
    )
    ind = facts.get("industry", {})
    add(
        "行业",
        75
        if ind.get("relative") == "个股弱于行业"
        else 25
        if ind.get("relative") == "个股强于行业"
        else 50
        if ind.get("relative") == "基本同步"
        else None,
        8,
        ind.get("relative", "缺失"),
    )
    fundamental = facts.get("fundamental", {})
    add(
        "基本面",
        min(100, 30 + 25 * len(fundamental.get("warnings", [])))
        if fundamental.get("rows")
        else None,
        10,
        "财务异常规则",
    )
    for name, key in (("新闻", "news"), ("公告", "announcements")):
        rows = facts.get(key, [])
        add(
            name,
            min(100, 30 + 25 * sum(bool(r.get("risk_flag")) for r in rows))
            if rows
            else None,
            6,
            "标题事件规则，仅为初筛",
        )
    flow = facts.get("moneyflow", {})
    amount = market.get("amount")
    net = flow.get("net_amount") if flow.get("date") == market.get("date") else None
    add(
        "资金流",
        max(0, -net / amount) * 500 if net is not None and amount else None,
        6,
        "主动资金净流出占成交额",
    )
    total = sum(x["weight"] for x in components)
    score = (
        round(sum(x["value"] * x["weight"] for x in components) / total)
        if total
        else None
    )
    stars = max(1, min(5, math.ceil(score / 20))) if score is not None else 0
    return {
        "score": score,
        "level": "HIGH" if score >= 65 else "MEDIUM" if score >= 35 else "LOW",
        "stars": "★" * stars + "☆" * (5 - stars),
        "reasons": [
            f"{x['name']}：{x['reason']}" for x in components if x["value"] >= 60
        ],
        "components": components,
        "missing": missing,
        "coverage": round(total / 100, 2),
        "note": "仅对可用因子归一化的启发式评分，不是损失概率；缺失数据不等于低风险。",
    }
