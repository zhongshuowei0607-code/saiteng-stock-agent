"""Deterministic explanations of existing facts when the model is unavailable."""

import math


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def data_coverage(facts: dict) -> dict:
    market = facts.get("market") or {}
    technical = facts.get("technical") or {}
    portfolio = facts.get("portfolio") or {}
    available = {
        "行情": any(_number(market.get(key)) for key in ("close", "open", "high", "low")),
        "技术指标": any(_number(technical.get(key)) for key in ("MA5", "MA20", "MA60", "RSI14", "MACD", "ATR")),
        "持仓": any(_number(portfolio.get(key)) for key in ("shares", "total_shares", "average_cost")),
        "财务": bool((facts.get("fundamental") or {}).get("rows")),
        "新闻": bool(facts.get("news")),
        "公告": bool(facts.get("announcements")),
        "资金流": _number((facts.get("moneyflow") or {}).get("net_amount")),
    }
    return {
        "available": [key for key, value in available.items() if value],
        "missing": [key for key, value in available.items() if not value],
        "has_core_facts": any(available[key] for key in ("行情", "技术指标", "持仓", "财务")),
    }


def rules_explanation(facts: dict, reason: str, reason_code: str, *, attempts: int = 0, retryable: bool = False) -> dict:
    """Quote program results; never infer missing market or event information."""
    coverage = data_coverage(facts)
    market = facts.get("market") or {}
    technical = facts.get("technical") or {}
    portfolio = facts.get("portfolio") or {}
    risk = facts.get("risk") or {}
    stable = facts.get("stabilization") or {}
    watch = facts.get("watch_zone") or {}
    trend_labels = {"STRONG_BULL": "强势", "BULL": "偏强", "SIDEWAYS": "震荡", "BEAR": "偏弱", "STRONG_BEAR": "弱势"}
    trend_parts = []
    for key, label in (("short", "短期"), ("medium", "中期"), ("long", "长期")):
        state = ((facts.get("trend") or {}).get(key) or {}).get("state")
        if state in trend_labels:
            trend_parts.append(f"{label}趋势规则判定为{trend_labels[state]}")
    trend = "；".join(trend_parts) or "趋势判定所需历史数据尚不完整，仅展示已有指标。"
    summary_parts = []
    if _number(market.get("close")):
        prefix = f"行情日期 {market['date']}，" if market.get("date") else ""
        summary_parts.append(f"{prefix}收盘价 {market['close']}")
    if trend_parts:
        summary_parts.append("；".join(trend_parts[:2]))
    if technical.get("volume_signal"):
        summary_parts.append(f"量价规则：{technical['volume_signal']}")
    if not summary_parts:
        indicators = [f"{key}={technical[key]}" for key in ("MA5", "MA20", "RSI14", "MACD") if _number(technical.get(key))]
        summary_parts.append("已有指标：" + "，".join(indicators) if indicators else "可用资料：" + "、".join(coverage["available"]))
    risk_text = f"程序风险评分 {risk['score']}；该评分并非损失概率。" if _number(risk.get("score")) else "风险评分所需事实不足，暂不判断风险高低。"
    if risk.get("missing"):
        risk_text += "缺少：" + "、".join(risk["missing"]) + "。"
    position_parts = []
    for key, label in (("shares", "持仓股数"), ("total_shares", "持仓股数"), ("average_cost", "持仓均价"), ("pnl_pct", "浮动盈亏百分比")):
        if _number(portfolio.get(key)):
            position_parts.append(f"{label} {portfolio[key]}")
    confirmed = [row["name"] for row in stable.get("signals", []) if row.get("confirmed") is True and row.get("name")]
    stabilization = f"程序企稳评分 {stable['score']}；不等同反转已确认。" if _number(stable.get("score")) else "企稳所需历史数据不足，等待更多行情。"
    focus = ["先核对行情日期与持仓是否最新，再核对计划触发条件。"]
    for key, label in (("support", "支撑"), ("resistance", "压力")):
        prices = [str(row["price"]) for row in (facts.get("levels") or {}).get(key, [])[:2] if _number(row.get("price"))]
        if prices:
            focus.append(f"观察价格与程序计算{label}位 {'、'.join(prices)} 的关系；触及价格不代表确认。")
    has_core = coverage["has_core_facts"]
    return {
        "status": "unavailable", "mode": "rules" if has_core else "unavailable",
        "label": "程序规则解读" if has_core else "资料待补全",
        "reason": reason, "reason_code": reason_code,
        "attempts": attempts, "retryable": retryable, "data_coverage": coverage,
        "summary": "程序规则解读：" + "；".join(summary_parts) + "。" if has_core else "暂无可用行情、技术指标、持仓或财务事实，请先更新数据。",
        "trend": trend, "risk": risk_text,
        "portfolio_analysis": "；".join(position_parts) or "持仓资料未提供，无法评估持仓状态。",
        "watch_zone": watch.get("message") or watch.get("state") or "观察区尚未形成，等待行情更新。",
        "stabilization": stabilization,
        "bullish_factors": ["已确认规则信号：" + name for name in confirmed[:3]],
        "bearish_factors": [str(item) for item in risk.get("reasons", [])[:3]],
        "next_day_focus": focus,
        "conclusion": "以上由程序引用已有事实生成；AI 解读暂不可用。缺失资料的部分保留判断，操作前核对当前行情与个人计划。",
        "events": [],
    }
