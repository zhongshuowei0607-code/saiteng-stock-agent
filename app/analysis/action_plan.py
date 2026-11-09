"""Deterministic, conditional plans shared by the dashboard and notifications.

Daily indicators describe completed bars. Only a time-stamped quote in a confirmed
trading session can make a plan eligible for an intraday notification.

Decision order (first match wins):
    data validity -> critical risk -> over position limit -> hard risk zone
    -> support break -> rebound trim -> risk warning (block adds) -> confirmed add.
Risk warning never forces a sale at a low price. Selling is only proposed for a
hard stop, a critical risk score, a support break, or a rebound into resistance.
"""

from datetime import datetime, time
from math import isfinite
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ACTION_PLAN = {
    "lot_size": 100,
    "first_add_fraction": 0.5,
    "second_add_fraction": 1.0,
    "breakout_add_fraction": 0.5,
    "rebound_sell_fraction": 0.2,
    "reduce_sell_fraction": 0.5,
    "break_support_sell_fraction": 0.5,
    "critical_sell_fraction": 1.0,
    "add_confirmation_days": 1,
    "block_add_trends": [],
}


def number(value, default=None):
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError):
        return default


def trading_hours(now: datetime) -> bool:
    now = now.astimezone(TZ)
    return now.weekday() < 5 and (
        time(9, 30) <= now.time().replace(tzinfo=None) < time(11, 30)
        or time(13) <= now.time().replace(tzinfo=None) < time(15)
    )


def quote_is_fresh(report: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    market = report.get("market") or {}
    if not market.get("is_realtime") or report.get("stale_data"):
        return False
    try:
        quoted = datetime.fromisoformat(market["quote_time"])
        if quoted.tzinfo is None:
            return False
        quoted = quoted.astimezone(TZ)
    except (KeyError, ValueError, TypeError):
        return False
    interval = number(report.get("monitor_interval_seconds"), 180)
    age_limit = min(600, max(180, interval * 2))
    age = (now - quoted).total_seconds()
    return (
        market.get("date") == now.date().isoformat() == quoted.date().isoformat()
        # The source timestamp can be a few seconds ahead of the caller's
        # clock while the HTTP response is in flight. A larger future gap is
        # rejected as a malformed quote.
        and -15 <= age <= age_limit
        and trading_hours(quoted)
    )


def _range(zone: dict) -> str:
    low, high = zone.get("min"), zone.get("max")
    if low is None:
        return f"低于 {high:g} 元" if number(high) is not None else "未配置"
    if high is None:
        return f"{low:g} 元及以上"
    return f"{low:g} ≤ 价格 < {high:g} 元"


def build_action_guide(report: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    now = now.replace(tzinfo=TZ) if now.tzinfo is None else now.astimezone(TZ)
    market, portfolio = report.get("market") or {}, report.get("portfolio") or {}
    price = number(market.get("close"))
    shares = max(0, int(number(portfolio.get("shares"), 0)))
    maximum = max(0, int(number(portfolio.get("max_shares"), 0)))
    remaining = max(0, maximum - shares)
    config = {**DEFAULT_ACTION_PLAN, **(report.get("action_plan") or {})}
    # This application tracks 603283 only; never turn a configuration typo into
    # a non-board-lot buy order or an order larger than the available position.
    lot = max(100, int(number(config.get("lot_size"), 100)) // 100 * 100)
    risk = number((report.get("risk") or {}).get("score"))
    risk_config = report.get("risk_config") or {}
    warning = number(risk_config.get("warning_threshold"), 65)
    critical = number(risk_config.get("critical_threshold"), 85)
    threshold = number(report.get("confirmation_score"), 7)
    stable = number((report.get("stabilization") or {}).get("score"))
    confirmation_days = max(1, int(number(config.get("add_confirmation_days"), 1)))
    block_add_trends = config.get("block_add_trends") or []
    if isinstance(block_add_trends, str):
        block_add_trends = [block_add_trends]
    trend_state = ((report.get("trend") or {}).get("medium") or {}).get("state")
    recent_closes = [
        value for value in (number(item) for item in (report.get("recent_closes") or []))
        if value is not None
    ]
    zones = report.get("position_zones") or []
    zone = next((z for z in zones if price is not None
                 and (z.get("min") is None or price >= z["min"])
                 and (z.get("max") is None or price < z["max"])), {})
    watch = report.get("watch_zone") or {}
    zone_state = zone.get("label") or watch.get("state", "未配置观察区")
    state = zone_state
    # Breakout and price-driven high risk are special states, not ordinary
    # price bands. Keep them authoritative over the matching zone label.
    if watch.get("state") in ("突破确认区", "高风险区"):
        state = watch["state"]
    # An event that only says "stop adding" is not a sell instruction.
    event_stop = watch.get("event_stop") is True or any(
        e.get("stop_adding_observation") is True for e in ((report.get("ai") or {}).get("events", []))
    )
    if event_stop:
        state = "事件风险"
    supports = [
        item for item in (report.get("levels") or {}).get("support", [])
        if number(item.get("price")) is not None
    ]
    # A stop-loss must use the strongest support, not the nearest pivot. The
    # nearest level is useful for observation but too noisy for a 50% sell.
    support_item = max(
        supports,
        key=lambda item: (number(item.get("strength"), 0), -number(item.get("price"), 0)),
        default=None,
    ) if supports else None
    support = number(support_item.get("price")) if support_item else None
    resistance = next((number(x.get("price")) for x in (report.get("levels") or {}).get("resistance", []) if number(x.get("price")) is not None), None)
    baseline_date = report.get("technical_as_of") or (report.get("technical") or {}).get("date") or market.get("date")
    blockers = []
    valid = price is not None and price > 0 and maximum > 0
    if price is None or price <= 0:
        blockers.append("缺少有效价格：先更新行情。")
    if maximum <= 0:
        blockers.append("持仓上限未配置：先在系统设置核对持仓。")
    if report.get("baseline_current") is False:
        valid = False
        blockers.append("日线基准尚未更新到最近交易日：先更新并生成日报。")
    fresh = quote_is_fresh(report, now)
    in_session = trading_hours(now) and report.get("trading_session_open") is True
    eligible = valid and fresh and in_session
    if not fresh:
        blockers.append("当前为收盘快照或实时报价已过期；仅作条件预案，等待新鲜报价。")
    if not in_session:
        blockers.append("交易时段或交易日尚未确认；盘中监测启动后再核对。")
    control_risk = any(
        "控制权变更" in (row.get("categories") or [])
        for key in ("announcements", "news")
        for row in report.get(key, [])
    )
    if control_risk:
        blockers.append("公告提示控制权可能变更：暂停加仓，先核对公告原文与后续安排。")

    def buy_quantity(base, fraction):
        fraction = min(1, max(0, number(config.get(fraction), 0)))
        return min(base, int(base * fraction // lot) * lot)

    def sell_quantity(base, fraction, *, full=False, minimum_one_lot=False):
        """Return an executable A-share sell quantity.

        A-share sell orders must be 100-share lots, except that an odd-lot
        balance below 100 shares may be sold in one order. A full exit is
        allowed even when the position is not a multiple of 100.
        """
        base = max(0, int(base))
        if base <= 0:
            return 0
        fraction = min(1, max(0, number(config.get(fraction), 0)))
        if full or fraction >= 1:
            return base
        target = int(base * fraction)
        if base < lot:
            return base
        if target < lot:
            return lot if minimum_one_lot else 0
        return min(base, target // lot * lot)

    checks = ["核对券商实时价格，确认触发条件仍成立。", "查看最新公告，确认没有新增重大事件。"]
    actions = []

    def add(category, signal, count, reason, price_range, invalidation):
        if count <= 0:
            if category == "buy":
                blockers.append("按当前配置计算不足一手，不自动放大参考股数；先核对仓位比例。")
            else:
                blockers.append("按当前比例不足一手；零股只能一次性卖出，先核对券商可卖数量。")
            return
        is_buy = category == "buy"
        actions.append({
            "category": category, "signal": signal,
            "direction": "买入条件核对" if is_buy else "减仓条件核对",
            "shares": count, "reason": reason, "price_range": price_range,
            "current_shares": shares, "shares_after": shares + count if is_buy else max(0, shares - count),
            "when": "当前交易时段，完成确认清单后自行决定" if eligible else "下一交易时段，实时条件重新满足后核对",
            "checks": checks + (["确认可用资金及费用，买入后不超过持仓上限。"] if is_buy else ["A 股卖出须为 100 股整数倍；不足 100 股的零股只能一次性卖出。", "核对券商可卖数量（含 T+1 限制）；本工具未获取可卖库存。"])
                      + ["成交后到系统设置更新实际买卖记录；参考计划不会自动记为成交。"],
            "invalidation": invalidation,
        })

    if valid:
        broken = support is not None and price < support
        risk_critical = risk is not None and risk >= critical
        risk_warning = risk is not None and risk >= warning
        if risk_critical:
            blockers.append("风险评分达到严重阈值，暂停加仓，优先核对风险与退出条件。")
            add("risk", "RISK_REVIEW", sell_quantity(shares, "critical_sell_fraction", full=True),
                f"风险评分 {risk:g} ≥ 严重阈值 {critical:g}",
                f"现价 {price:g} 元，先核实风险原因与公告原文",
                "风险评分回落到严重阈值以下且事件风险解除后，才能重新评估。")
        elif shares > maximum:
            excess = shares - maximum
            odd = shares % lot
            count = excess if odd and excess <= odd else min(shares, ((excess + lot - 1) // lot) * lot)
            add("risk", "RISK_REVIEW", count,
                f"持仓 {shares} 股超过上限 {maximum} 股，先减至上限以内",
                f"现价 {price:g} 元附近，优先核对超限部分",
                "持仓回到上限以内后，本条计划失效。")
        elif state == "高风险区":
            blockers.append("高风险区：暂停加仓，优先核对硬止损与已有持仓。")
            add("risk", "RISK_REVIEW", sell_quantity(shares, "break_support_sell_fraction", minimum_one_lot=True),
                f"进入{state}；风险评分 {risk if risk is not None else '未评估'}",
                f"现价 {price:g} 元，先核实风险原因",
                "重新站回风险区上沿、风险评分回落且企稳确认后，才能重新评估。")
        elif broken:
            add("sell", "BREAK_SUPPORT", sell_quantity(shares, "break_support_sell_fraction", minimum_one_lot=True),
                f"实时价格低于基准支撑 {support:g} 元", f"低于 {support:g} 元",
                f"价格收回 {support:g} 元以上或支撑基准更新后重新评估。")
        elif state in ("反弹观察区", "反弹减仓观察区") or (
            state == "事件风险" and zone_state in ("反弹观察区", "反弹减仓观察区")
        ):
            second = zone_state == "反弹减仓观察区"
            add("sell", "SELL_WATCH_LEVEL_2" if second else "SELL_WATCH_LEVEL_1",
                sell_quantity(shares, "reduce_sell_fraction" if second else "rebound_sell_fraction"),
                f"进入{zone_state}，按已配置持仓比例复核", _range(zone),
                "离开该价格区间，或持仓已变化时，原参考股数失效。")
        elif state == "事件风险":
            blockers.append("重大事件风险触发：暂停加仓；是否减仓只按硬止损、反弹减仓或风险阈值执行。")
        elif risk_warning:
            blockers.append(f"风险评分 {risk:g} ≥ 警戒 {warning:g}，暂停加仓；等待风险回落或反弹减仓条件。")
        elif control_risk:
            pass
        elif state in ("第一加仓观察区", "第二加仓观察区", "突破确认区"):
            zone_floor = number(zone.get("min"))
            if trend_state in block_add_trends:
                blockers.append(f"中期趋势 {trend_state} 偏空，暂停加仓；等待趋势修复。")
            elif risk is None:
                blockers.append("风险评分缺失，暂不形成加仓计划。")
            elif (
                state != "突破确认区"
                and zone_floor is not None
                and len(recent_closes) >= confirmation_days
                and not all(
                    value > zone_floor
                    for value in recent_closes[-confirmation_days:]
                )
            ):
                blockers.append(
                    f"需连续 {confirmation_days} 日收于 {zone_floor:g} 元上方，当前未满足；不追单日反弹。"
                )
            elif stable is None or stable < threshold:
                blockers.append(f"企稳 {stable if stable is not None else '缺失'}/10，需达到 {threshold:g}/10 才核对加仓。")
            elif remaining < lot:
                blockers.append("剩余额度不足一手，暂停加仓。")
            else:
                key = {"第一加仓观察区": "first_add_fraction", "第二加仓观察区": "second_add_fraction", "突破确认区": "breakout_add_fraction"}[state]
                signal = {"第一加仓观察区": "BUY_WATCH_LEVEL_1", "第二加仓观察区": "BUY_WATCH_LEVEL_2", "突破确认区": "BREAKOUT_CONFIRMED"}[state]
                add("buy", signal, buy_quantity(remaining, key),
                    f"{state}；企稳达到 {threshold:g}/10；风险低于 {warning:g}", _range(zone),
                    "跌破支撑、风险升高、重大事件出现、离开区间或实际持仓变化时取消此预案。")

    scenarios = []
    for z in zones:
        label = z.get("label", "观察")
        if "加仓" in label:
            action = f"先检查企稳≥{threshold:g}/10、风险<{warning:g}及剩余额度，满足后再核对买入股数。"
        elif "反弹" in label:
            action = "核对分批减仓条件、券商可卖数量与当前持仓；参考股数按配置重新计算。"
        elif "风险" in label:
            action = "暂停加仓，优先核对风险与减仓预案。"
        else:
            action = "维持观察，等价格或风险触发其他条件。"
        scenarios.append({"title": label, "condition": _range(z), "action": action, "invalidation": "实时价格离开该区间或基准更新后失效。"})
    if support is not None:
        scenarios.insert(0, {"title": "支撑失守优先", "condition": f"价格低于 {support:g} 元", "action": "先核实实时行情，再检查减仓条件；暂停加仓。", "invalidation": "重新站回支撑或更新基准后复核。"})
    if control_risk:
        scenarios.insert(0, {"title": "控制权变更风险", "condition": "公告提示控制权可能变更，后续安排尚未明确", "action": "暂停加仓，核对公告原文、协商进展与控制权稳定性；是否减仓只按硬止损或风险阈值执行。", "invalidation": "控制权安排明确且风险评分回落后重新评估。"})
    if state == "突破确认区" and resistance is not None:
        scenarios.insert(0, {"title": "突破确认区", "condition": f"价格站上 {resistance:g} 元且连续两日不回落、成交量高于五日均量", "action": f"仅当企稳≥{threshold:g}/10、风险<{warning:g}且剩余额度≥{lot}股时核对加仓；单日冲高不追。", "invalidation": "跌回压力位下方或放量失败时取消。"})
    if resistance is not None:
        scenarios.append({"title": "压力突破观察", "condition": f"价格高于 {resistance:g} 元", "action": "若处于反弹减仓区，优先核对减仓；若在加仓区，等待收盘与放量确认后再核对。", "invalidation": "回落到压力以下则取消突破观察。"})
    scenarios.append({"title": "风险升级优先", "condition": f"风险评分 ≥ {critical:g} 或出现控制权、质押、监管等重大事件", "action": "暂停加仓，优先核对减仓或退出；不以技术反弹为由逆势加仓。", "invalidation": "事件明确解除且风险评分回落后重新评估。"})
    scheduler = report.get("schedule_config") or {}
    daily_time = f"{int(scheduler.get('hour', 17)):02d}:{int(scheduler.get('minute', 30)):02d}"
    status = "blocked" if not valid else "review" if actions and eligible else "wait"
    if not valid:
        title = "先更新数据与持仓"
    elif actions:
        title = "先核对减仓条件" if actions[0]["category"] != "buy" else "先核对加仓条件"
    elif state == "事件风险" or control_risk:
        title = "事件风险：暂停加仓，先核对公告"
    elif state in ("第一加仓观察区", "第二加仓观察区", "突破确认区") and remaining < lot:
        title = "已接近或达到持仓上限"
    elif state in ("第一加仓观察区", "第二加仓观察区", "突破确认区"):
        title = "暂停加仓，等待风险与企稳条件"
    elif state == "高风险区":
        title = "高风险：先核对止损与持仓"
    else:
        title = "保持观察，等待条件满足"
    if not eligible and valid and state != "事件风险" and not control_risk:
        title = "收盘复盘：准备下一交易时段" if not in_session else "等待有效实时报价"
    summary_fallback = "当前未形成可执行的条件计划；按下方检查点跟踪。"
    if not valid:
        summary_fallback = "数据或持仓上限不完整，先补齐后再判断。"
    elif state == "事件风险":
        summary_fallback = "重大事件风险触发，暂停加仓；按硬止损或反弹减仓条件核对，不把标题级事件当作卖出指令。"
    elif state in ("第一加仓观察区", "第二加仓观察区", "突破确认区"):
        reasons = [b for b in blockers if b.startswith(("公告提示控制权", "风险评分", "企稳", "剩余额度"))]
        if reasons:
            summary_fallback = "；".join(reasons[:2]) + "；按下方检查点跟踪。"
    return {
        "status": status, "title": title,
        "summary": (actions[0]["reason"] + f"；参考 {actions[0]['shares']} 股，须人工确认。") if actions else summary_fallback,
        "data_as_of": str(market.get("date") or "缺失"), "quote_time": market.get("quote_time"),
        "technical_as_of": baseline_date, "state": state, "eligible_for_alert": eligible,
        "actions": actions, "blockers": blockers, "scenarios": scenarios,
        "checkpoints": [f"支撑：{support:g} 元" if support else "支撑尚未形成", f"压力：{resistance:g} 元" if resistance else "压力尚未形成", f"企稳门槛：{threshold:g}/10；风险警戒：{warning:g}/100；严重阈值：{critical:g}/100", f"持仓 {shares} 股 / 上限 {maximum} 股；剩余 {remaining} 股"],
        "schedule": [
            {"time": "开盘前", "task": "核对持仓、可卖数量、公告；确认本机服务与邮件已启用。"},
            {"time": "09:30–11:30 / 13:00–15:00", "task": f"交易日每 {report.get('monitor_interval_seconds', 180)} 秒检查实时报价；新条件触发时邮件提醒。"},
            {"time": "收到提醒时", "task": "核对触发时间、价格、股数与失效条件，再自行决定；成交后登记记录。"},
            {"time": f"交易日 {daily_time}", "task": "生成收盘分析并发送一次日报；查看下一交易日条件计划。"},
        ],
    }
