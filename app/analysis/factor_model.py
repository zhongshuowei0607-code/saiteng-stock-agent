"""Research-only single-stock factor snapshot.

This is deliberately a time-series factor panel, not a cross-sectional stock
selection model. It turns existing facts into transparent 0-100 scores so the
user can see why the composite is bullish/bearish before any v2 strategy is
allowed to affect the live plan.
"""

from __future__ import annotations

from math import isnan

FACTOR_WEIGHTS = {
    "reversal": 0.16,
    "momentum": 0.16,
    "volatility": 0.13,
    "relative_strength": 0.13,
    "quality": 0.11,
    "growth": 0.09,
    "valuation": 0.06,
    "liquidity": 0.06,
    # Event is a veto overlay, not an alpha weight.
    "event": 0.0,
}


def _num(value):
    try:
        result = float(value)
        return result if result == result and not isnan(result) else None
    except (TypeError, ValueError):
        return None


def _clamp(value, low=0.0, high=100.0):
    return round(max(low, min(high, value)), 2)


def _percentile(series, value, inverse=False):
    values = [item for item in series if item is not None and item == item]
    if len(values) < 60 or value is None:
        return None
    rank = sum(1 for item in values if item <= value) / len(values) * 100
    return 100 - rank if inverse else rank


def _factor(name, score, reason, available=True):
    return {
        "name": name,
        "label": {
            "reversal": "反转",
            "momentum": "动量",
            "volatility": "波动率",
            "relative_strength": "相对强弱",
            "quality": "质量",
            "growth": "成长",
            "valuation": "估值",
            "liquidity": "流动性",
            "event": "事件",
        }.get(name, name),
        "score": _clamp(score) if score is not None else None,
        "weight": FACTOR_WEIGHTS.get(name, 0.0),
        "available": bool(available and score is not None),
        "reason": reason,
    }


def _rows_with_value(rows, key):
    return [
        row for row in rows
        if _num(row.get(key)) is not None and _num(row.get(key)) > 0
    ]


def _relative_factor(report):
    industry = report.get("industry") or {}
    rows = industry.get("rows") or []
    target = (report.get("stock") or {}).get("code")
    target_row = next((row for row in rows if row.get("code") == target), None)
    if not target_row or len(rows) < 3:
        return None, "同行样本不足3只"
    values = [_num(row.get("return20")) for row in rows]
    value = _num(target_row.get("return20"))
    if value is None or len([x for x in values if x is not None]) < 3:
        return None, "20日相对收益缺失"
    ordered = sorted([x for x in values if x is not None], reverse=True)
    rank = ordered.index(value) + 1
    score = 100 * (1 - (rank - 1) / max(1, len(ordered) - 1))
    return score, f"20日涨幅在{len(ordered)}只样本中排名 {rank}"


def _valuation_factor(report):
    industry = report.get("industry") or {}
    rows = _rows_with_value(industry.get("rows") or [], "pe")
    target = (report.get("stock") or {}).get("code")
    target_row = next((row for row in rows if row.get("code") == target), None)
    pe = _num(target_row.get("pe")) if target_row else _num((report.get("market") or {}).get("pe"))
    if pe is None or len(rows) < 3:
        return None, "PE 或同行样本不足"
    ordered = sorted(_num(row.get("pe")) for row in rows)
    rank = sum(1 for item in ordered if item < pe) + 1
    score = 100 * (1 - (rank - 1) / max(1, len(ordered) - 1))
    return score, f"PE {pe:.2f}，同行分位约 {rank}/{len(ordered)}"


def _quality_factor(report):
    fundamental = report.get("fundamental") or {}
    if not fundamental.get("rows"):
        return None, "财务数据不足"
    warnings = fundamental.get("warnings") or []
    score = 100 - 20 * len(warnings)
    changes = fundamental.get("yoy_changes") or {}
    ocf = _num(changes.get("operating_cashflow"))
    if ocf is not None and ocf < 0:
        score -= 15
    reason = f"财务预警 {len(warnings)} 项" + (
        f"，经营现金流同比 {ocf:+.1f}%" if ocf is not None else ""
    )
    return score, reason


def _growth_factor(report):
    fundamental = report.get("fundamental") or {}
    rows = fundamental.get("rows") or []
    if not rows:
        return None, "财务数据不足"
    latest = rows[0]
    values = [
        _num(latest.get("profit_yoy")),
        _num(latest.get("revenue_yoy")),
    ]
    changes = fundamental.get("yoy_changes") or {}
    if all(value is None for value in values):
        values = [_num(changes.get("net_profit"))]
    values = [value for value in values if value is not None]
    if not values:
        return None, "同比增速缺失"
    growth = sum(values) / len(values)
    return _clamp(50 + growth * 1.5), f"可用同比增速均值 {growth:+.1f}%"


def _event_factor(report):
    rows = (report.get("announcements") or []) + (report.get("news") or [])
    categories = [
        category
        for row in rows
        for category in (row.get("categories") or [])
    ]
    control = any("控制权变更" in categories for category in categories)
    risk_count = sum(1 for row in rows if row.get("risk_flag"))
    score = 0 if control else max(0, 100 - 25 * risk_count)
    reason = (
        "控制权变更事件，暂停新增风险"
        if control
        else f"风险类标题/正文 {risk_count} 条"
    )
    return score, reason, control


def build_factor_snapshot(technical, report):
    """Compute a transparent factor panel from a completed daily frame."""
    report = report or {}
    factors = []
    has_close = (
        technical is not None
        and not technical.empty
        and "close" in technical.columns
    )
    close = technical["close"].dropna() if has_close else None
    returns20 = close.pct_change(20) if close is not None else None
    returns60 = close.pct_change(60) if close is not None else None
    current20 = _num(returns20.iloc[-1]) if returns20 is not None and len(returns20) else None
    current60 = _num(returns60.iloc[-1]) if returns60 is not None and len(returns60) else None
    score = _percentile(returns20.tolist() if returns20 is not None else [], current20, inverse=True)
    factors.append(_factor("reversal", score, f"20日收益 {current20 * 100:+.2f}%，历史分位反向" if current20 is not None else "20日收益缺失", score is not None))
    score = _percentile(returns60.tolist() if returns60 is not None else [], current60, inverse=False)
    factors.append(_factor("momentum", score, f"60日收益 {current60 * 100:+.2f}%，历史分位" if current60 is not None else "60日收益缺失", score is not None))

    atr = _num((technical["ATR"].iloc[-1] if "ATR" in technical else None)) if technical is not None and len(technical) else None
    price = _num(close.iloc[-1]) if close is not None and len(close) else None
    atr_pct = None
    if atr is not None and price:
        ratio = technical["ATR"] / technical["close"]
        atr_pct = _num(ratio.iloc[-1])
        score = _percentile([_num(x) for x in ratio.tolist()], atr_pct, inverse=True)
    else:
        score = None
    factors.append(_factor("volatility", score, f"ATR/价格 {atr_pct * 100:.2f}%" if atr_pct is not None else "ATR 缺失", score is not None))

    relative_score, relative_reason = _relative_factor(report)
    factors.append(_factor("relative_strength", relative_score, relative_reason, relative_score is not None))

    quality_score, quality_reason = _quality_factor(report)
    factors.append(_factor("quality", quality_score, quality_reason, quality_score is not None))

    growth_score, growth_reason = _growth_factor(report)
    factors.append(_factor("growth", growth_score, growth_reason, growth_score is not None))

    valuation_score, valuation_reason = _valuation_factor(report)
    factors.append(_factor("valuation", valuation_score, valuation_reason, valuation_score is not None))

    turnover = _num(technical["turnover"].iloc[-1]) if technical is not None and "turnover" in technical and len(technical) else None
    if turnover is not None and technical is not None:
        values = [_num(x) for x in technical["turnover"].tolist()]
        score = _percentile(values, turnover, inverse=True)
    else:
        score = None
    factors.append(_factor("liquidity", score, f"换手率 {turnover:.2f}%，低换手方向（有争议）" if turnover is not None else "换手率缺失", score is not None))

    event_score, event_reason, event_veto = _event_factor(report)
    factors.append(_factor("event", event_score, event_reason, True))

    weights = sum(item["weight"] for item in factors if item["available"])
    total_weight = sum(item["weight"] for item in factors)
    composite = (
        sum(item["score"] * item["weight"] for item in factors if item["available"]) / weights
        if weights else None
    )
    if event_veto and composite is not None:
        composite = min(composite, 35)
    coverage = round(weights / total_weight, 2) if total_weight else 0.0
    if event_veto:
        status, bias = "event_veto", "事件否决"
    elif composite is None:
        status, bias = "unavailable", "数据不足"
    elif coverage < 0.6:
        status, bias = "low_confidence", "低置信度"
    elif composite >= 60:
        status, bias = "ok", "偏多"
    elif composite <= 40:
        status, bias = "ok", "偏空"
    else:
        status, bias = "ok", "中性"
    history_bars = len(close) if close is not None else 0
    confidence = "high" if coverage >= 0.75 and history_bars >= 250 else "medium" if coverage >= 0.5 else "low"
    missing = [item["label"] for item in factors if not item["available"]]
    trend = report.get("trend") or {}
    summary = (
        f"单票因子综合 {composite:.1f}/100，{bias}；覆盖率 {coverage:.0%}，"
        f"置信度 {confidence}。中期趋势 "
        f"{'偏弱' if (trend.get('medium') or {}).get('state') in ('BEAR', 'STRONG_BEAR') else '非弱势'}。"
        if composite is not None
        else "因子数据不足，暂不形成综合评分。"
    )
    return {
        "version": "factor-v1",
        "as_of": str((report.get("technical") or {}).get("date") or ""),
        "history_bars": int(history_bars),
        "composite": round(composite, 2) if composite is not None else None,
        "bias": bias,
        "status": status,
        "confidence": confidence,
        "coverage": coverage,
        "event_veto": event_veto,
        "factors": factors,
        "missing": missing,
        "summary": summary,
        "note": "单票时间序列因子，不是横截面选股；仅研究，不直接改变 v1 操作计划。",
    }
