import html
import json
import os
import tempfile
from pathlib import Path
import markdown
from .sanitize import sanitize

DISCLAIMER = "本系统仅用于个人研究，不构成投资建议。"
SECTIONS = [
    ("一、今日行情", "market"),
    ("二、技术趋势", "trend"),
    ("三、我的持仓", "portfolio"),
    ("四、盈亏情况", "pnl"),
    ("五、支撑位 / 压力位", "levels"),
    ("六、当前仓位观察状态", "watch_zone"),
    ("七、企稳评分", "stabilization"),
    ("八、公告", "announcements"),
    ("九、新闻", "news"),
    ("十、行业强弱", "industry"),
    ("十一、基本面变化", "fundamental"),
    ("十二、风险评分", "risk"),
    ("十三、AI总结", "ai"),
    ("十四、下一交易日重点观察", "focus"),
]

LABELS = {
    "open": "开盘价",
    "close": "收盘价",
    "high": "最高价",
    "low": "最低价",
    "pre_close": "前收盘价",
    "change": "涨跌额",
    "pct_change": "涨跌幅（%）",
    "date": "日期",
    "volume": "成交量（手）",
    "amount": "成交额（元）",
    "turnover": "换手率（%）",
    "pe": "PE",
    "pb": "PB",
    "total_mv": "总市值（元）",
    "circ_mv": "流通市值（元）",
    "source": "来源",
    "shares": "持仓股数",
    "total_cost": "总成本（元）",
    "average_cost": "平均成本（元）",
    "market_value": "当前市值（元）",
    "pnl": "浮盈亏（元）",
    "pnl_pct": "浮盈亏比例（%）",
    "max_shares": "最大计划股数",
    "remaining_shares": "剩余计划股数",
    "position_ratio": "计划仓位比例",
    "over_limit": "是否超过计划上限",
    "short": "短线",
    "medium": "中线",
    "long": "长线",
    "state": "状态",
    "score": "评分",
    "level": "级别",
    "stars": "风险星级",
    "message": "说明",
    "confirmed": "是否达到观察阈值",
    "summary": "摘要",
    "trend": "趋势解释",
    "risk": "风险解释",
    "portfolio_analysis": "持仓解释",
    "watch_zone": "观察区",
    "stabilization": "企稳解释",
    "conclusion": "结论",
    "status": "状态",
    "next_day_focus": "下一交易日观察",
    "bullish_factors": "偏多因素",
    "bearish_factors": "偏空因素",
    "coverage": "风险因子覆盖率",
    "missing": "缺失因子",
    "note": "口径说明",
    "reasons": "依据",
    "signals": "企稳信号",
    "support": "支撑",
    "resistance": "压力",
    "end_date": "报告期",
    "announcement_date": "公告日",
    "revenue": "营业收入（元）",
    "revenue_yoy": "营收同比（%）",
    "net_profit": "归母净利润（元）",
    "profit_yoy": "净利润同比（%）",
    "deducted_profit": "扣非净利润（元）",
    "gross_margin": "毛利率（%）",
    "net_margin": "净利率（%）",
    "roe": "ROE（%）",
    "operating_cashflow": "经营现金流（元）",
    "receivables": "应收账款（元）",
    "inventory": "存货（元）",
    "contract_liabilities": "合同负债（元）",
    "total_assets": "总资产（元）",
    "total_liabilities": "总负债（元）",
    "debt_ratio": "资产负债率（%）",
}


def display(value: object) -> str:
    if value is None:
        return "数据不足，无法判断。"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return str(value).replace("|", " / ").replace("\n", " ")


def table(value: dict) -> str:
    rows = ["| 项目 | 结果 |", "| --- | --- |"]
    for key, item in value.items():
        if not isinstance(item, (dict, list)):
            rows.append(f"| {LABELS.get(key, key)} | {display(item)} |")
    return "\n".join(rows)


def section(key: str, value: object) -> str:
    if not value:
        return "数据不足，无法判断。"
    if key in ("news", "announcements"):
        return "\n\n".join(
            f"**{item['title']}**\n\n{item.get('date', '')} · {item.get('source', '')} · {item.get('analysis_scope', '')}\n\n原文链接：{item.get('url', '')}"
            for item in value
        )
    if key == "trend":
        return "\n\n".join(
            f"**{LABELS[name]}**\n\n"
            + table(row)
            + "\n\n"
            + "；".join(row.get("reasons", []))
            for name, row in value.items()
        )
    if key == "levels":
        return (
            "\n\n".join(
                "**"
                + LABELS[name]
                + "**\n\n"
                + "\n".join(
                    f"- {row['price']:.2f} 元；强度 {row['strength']}；{row['reason']}"
                    for row in value[name]
                )
                for name in ("support", "resistance")
            )
            + "\n\n"
            + value.get("note", "")
        )
    if key == "fundamental":
        return (
            (table(value["rows"][0]) if value.get("rows") else "数据不足，无法判断。")
            + "\n\n"
            + "；".join(value.get("warnings", []))
            + "\n\n"
            + value.get("note", "")
        )
    if key == "industry":
        text = value.get("relative", "数据不足，无法判断。")
        if value.get("rows"):
            text += "\n\n| 股票 | 当日（%） | 5日（%） | 20日（%） | 涨幅排名 | 强弱排名 |\n| --- | --- | --- | --- | --- | --- |\n"
            text += "\n".join(
                "| "
                + " | ".join(
                    display(row.get(field))
                    for field in (
                        "name",
                        "pct_change",
                        "return5",
                        "return20",
                        "daily_rank",
                        "strength_rank",
                    )
                )
                + " |"
                for row in value["rows"]
            )
        return text
    if isinstance(value, dict):
        text = table(value)
        for name, items in value.items():
            if isinstance(items, list) and items:
                if name == "signals":
                    text += "\n\n" + "\n".join(
                        f"- {'✓' if item['confirmed'] else '·'} {item['name']}"
                        for item in items
                    )
                elif name not in ("components", "events"):
                    text += (
                        "\n\n**"
                        + LABELS.get(name, name)
                        + "**\n\n"
                        + "\n".join("- " + display(item) for item in items)
                    )
        if value.get("events"):
            text += "\n\n**AI 事件解释**\n\n" + "\n\n".join(
                table(event) for event in value["events"]
            )
        return text
    if isinstance(value, list):
        return "\n".join("- " + display(item) for item in value)
    return display(value)


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as temporary:
        temporary.write(content)
        name = temporary.name
    try:
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def render_reports(report: dict, root: Path) -> tuple[Path, Path]:
    code = report["stock"]["code"][:6]
    folder = root / code
    folder.mkdir(parents=True, exist_ok=True)
    pieces = [
        f"# {code} {report['stock']['name']}每日跟踪报告",
        f"生成日期：{report['date']}；行情日期：{report.get('market', {}).get('date', '缺失')}",
        "数据状态：" + "；".join(report.get("warnings", [])),
    ]
    values = {
        **report,
        "pnl": {
            k: report["portfolio"].get(k) for k in ("market_value", "pnl", "pnl_pct")
        },
        "focus": report.get("ai", {}).get(
            "next_day_focus",
            ["核对行情日期、企稳信号和公告原文；数据不足的项目暂不判断。"],
        ),
    }
    for title, key in SECTIONS:
        value = values.get(key)
        pieces.extend(["## " + title, section(key, value)])
    pieces.extend(
        [
            "## 昨日观点对比",
            "```json\n"
            + json.dumps(report.get("comparison", {}), ensure_ascii=False, indent=2)
            + "\n```",
            "## 十五、免责声明",
            DISCLAIMER,
        ]
    )
    text = "\n\n".join(pieces)
    md = folder / (report["date"] + ".md")
    page = folder / (report["date"] + ".html")
    atomic_write(md, text)
    # 先转义全部外部文本，Markdown 围栏也不能成为 HTML 注入通道。
    body = sanitize(
        markdown.markdown(html.escape(text), extensions=["fenced_code", "tables"])
    )
    atomic_write(
        page,
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>赛腾股份日报</title><style>body{max-width:1000px;margin:40px auto;padding:20px;font:16px/1.7 system-ui;color:#203040}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:20px;border-radius:8px}h2{border-bottom:1px solid #ccd5df}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #dce3e9;padding:9px;text-align:left}th{background:#f1f5f8}</style>'
        + body
        + "</html>",
    )
    return md, page
