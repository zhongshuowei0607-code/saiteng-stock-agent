"""Deterministic, conditional plans shared by the dashboard and notifications.

Daily indicators describe completed bars. Only a time-stamped quote in a confirmed
trading session can make a plan eligible for an intraday notification.
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
    "stabilization_add_fraction": 0.25,
    "rebound_sell_fraction": 0.2,
    "reduce_sell_fraction": 0.5,
    "break_support_sell_fraction": 0.5,
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
        and 0 <= age <= age_limit
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
    threshold = number(report.get("confirmation_score"), 7)
    stable = number((report.get("stabilization") or {}).get("score"))
    zones = report.get("position_zones") or []
    zone = next((z for z in zones if price is not None
                 and (z.get("min") is None or price >= z["min"])
                 and (z.get("max") is None or price < z["max"])), {})
    state = zone.get("label") or (report.get("watch_zone") or {}).get("state", "未配置观察区")
    events = (report.get("ai") or {}).get("events", [])
    event_stop = any(e.get("stop_adding_observation") is True for e in events)
    if event_stop or (report.get("watch_zone") or {}).get("state") == "高风险区":
        state = "高风险区"
    support = next((number(x.get("price")) for x in (report.get("levels") or {}).get("support", []) if number(x.get("price")) is not None), None)
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

    def quantity(base, fraction):
        fraction = min(1, max(0, number(config.get(fraction), 0)))
        return min(base, int(base * fraction // lot) * lot)

    checks = ["核对券商实时价格，确认触发条件仍成立。", "查看最新公告，确认没有新增重大事件。"]
    actions = []

    def add(category, signal, count, reason, price_range, invalidation):
        if count <= 0:
            blockers.append("按当前配置计算不足一手，不自动放大参考股数；先核对仓位比例。")
            return
        is_buy = category == "buy"
        actions.append({
            "category": category, "signal": signal,
            "direction": "买入条件核对" if is_buy else "减仓条件核对",
            "shares": count, "reason": reason, "price_range": price_range,
            "current_shares": shares, "shares_after": shares + count if is_buy else shares - count,
            "when": "当前交易时段，完成确认清单后自行决定" if eligible else "下一交易时段，实时条件重新满足后核对",
            "checks": checks + (["确认可用资金及费用，买入后不超过持仓上限。"] if is_buy else ["核对券商可卖数量（含 T+1 限制）；本工具未获取可卖库存。"])
                      + ["成交后到系统设置更新实际买卖记录；参考计划不会自动记为成交。"],
            "invalidation": invalidation,
        })

    if valid:
        high_risk = state == "高风险区" or (risk is not None and risk >= warning)
        broken = support is not None and price < support
        # Mutually exclusive priorities: risk > support > rebound > confirmed add.
        if high_risk or shares > maximum:
            blockers.append("暂停加仓，优先核对风险及已有持仓。")
            add("risk", "RISK_REVIEW", quantity(shares, "reduce_sell_fraction"),
                "持仓超过上限" if shares > maximum else f"{state}；风险评分 {risk if risk is not None else '未评估'}",
                f"现价 {price:g} 元，先核实风险原因", "风险解除后重新生成计划，不能沿用本条减仓预案。")
        elif broken:
            add("sell", "BREAK_SUPPORT", quantity(shares, "break_support_sell_fraction"),
                f"实时价格低于基准支撑 {support:g} 元", f"低于 {support:g} 元",
                f"价格收回 {support:g} 元以上或支撑基准更新后重新评估。")
        elif state in ("反弹观察区", "反弹减仓观察区"):
            second = state == "反弹减仓观察区"
            add("sell", "SELL_WATCH_LEVEL_2" if second else "SELL_WATCH_LEVEL_1",
                quantity(shares, "reduce_sell_fraction" if second else "rebound_sell_fraction"),
                f"进入{state}，按已配置持仓比例复核", _range(zone),
                "离开该价格区间，或持仓已变化时，原参考股数失效。")
        elif state in ("第一加仓观察区", "第二加仓观察区", "突破确认区"):
            if risk is None:
                blockers.append("风险评分缺失，暂不形成加仓计划。")
            elif stable is None or stable < threshold:
                blockers.append(f"企稳 {stable if stable is not None else '缺失'}/10，需达到 {threshold:g}/10 才核对加仓。")
            elif remaining < lot:
                blockers.append("剩余额度不足一手，暂停加仓。")
            else:
                key = {"第一加仓观察区": "first_add_fraction", "第二加仓观察区": "second_add_fraction", "突破确认区": "breakout_add_fraction"}[state]
                signal = {"第一加仓观察区": "BUY_WATCH_LEVEL_1", "第二加仓观察区": "BUY_WATCH_LEVEL_2", "突破确认区": "BREAKOUT_CONFIRMED"}[state]
                add("buy", signal, quantity(remaining, key),
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
    if resistance is not None:
        scenarios.append({"title": "压力突破观察", "condition": f"价格高于 {resistance:g} 元", "action": "单次越过压力不形成买入；等待收盘与放量确认。", "invalidation": "回落到压力以下则取消突破观察。"})
    scheduler = report.get("schedule_config") or {}
    daily_time = f"{int(scheduler.get('hour', 17)):02d}:{int(scheduler.get('minute', 30)):02d}"
    status = "blocked" if not valid else "review" if actions and eligible else "wait"
    title = "先更新数据与持仓" if not valid else "先核对减仓条件" if actions and actions[0]["category"] != "buy" else "先核对加仓条件" if actions else "保持观察，等待条件满足"
    if not eligible and valid:
        title = "收盘复盘：准备下一交易时段" if not in_session else "等待有效实时报价"
    return {
        "status": status, "title": title,
        "summary": (actions[0]["reason"] + f"；参考 {actions[0]['shares']} 股，须人工确认。") if actions else "当前未形成可执行的条件计划；按下方检查点跟踪。",
        "data_as_of": str(market.get("date") or "缺失"), "quote_time": market.get("quote_time"),
        "technical_as_of": baseline_date, "eligible_for_alert": eligible,
        "actions": actions, "blockers": blockers, "scenarios": scenarios,
        "checkpoints": [f"支撑：{support:g} 元" if support else "支撑尚未形成", f"压力：{resistance:g} 元" if resistance else "压力尚未形成", f"企稳门槛：{threshold:g}/10；风险警戒：{warning:g}/100", f"持仓 {shares} 股 / 上限 {maximum} 股；剩余 {remaining} 股"],
        "schedule": [
            {"time": "开盘前", "task": "核对持仓、可卖数量、公告；确认本机服务与邮件已启用。"},
            {"time": "09:30–11:30 / 13:00–15:00", "task": f"交易日每 {report.get('monitor_interval_seconds', 180)} 秒检查实时报价；新条件触发时邮件提醒。"},
            {"time": "收到提醒时", "task": "核对触发时间、价格、股数与失效条件，再自行决定；成交后登记记录。"},
            {"time": f"交易日 {daily_time}", "task": "生成收盘分析并发送一次日报；查看下一交易日条件计划。"},
        ],
    }
