import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
from .bounded import fetch
from app.database.repository import clean

# 源字段显式映射；不把不存在的财务数据补零。
TS_MAP = {
    "total_revenue": "revenue",
    "revenue": "revenue",
    "revenue_yoy": "revenue_yoy",
    "netprofit_yoy": "profit_yoy",
    "n_income_attr_p": "net_profit",
    "profit_dedt": "deducted_profit",
    "grossprofit_margin": "gross_margin",
    "netprofit_margin": "net_margin",
    "roe": "roe",
    "n_cashflow_act": "operating_cashflow",
    "accounts_receiv": "receivables",
    "inventories": "inventory",
    "contract_liab": "contract_liabilities",
    "total_assets": "total_assets",
    "total_liab": "total_liabilities",
    "debt_to_assets": "debt_ratio",
}
EM_MAP = {
    "TOTALOPERATEREVE": "revenue",
    "TOTALOPERATEREVETZ": "revenue_yoy",
    "PARENTNETPROFIT": "net_profit",
    "PARENTNETPROFITTZ": "profit_yoy",
    "KCFJCXSYJLR": "deducted_profit",
    "XSMLL": "gross_margin",
    "XSJLL": "net_margin",
    "ROEJQ": "roe",
    "NETCASH_OPERATE": "operating_cashflow",
    "ACCOUNTS_RECE": "receivables",
    "INVENTORY": "inventory",
    "CONTRACT_LIAB": "contract_liabilities",
    "TOTAL_ASSETS": "total_assets",
    "TOTAL_LIABILITIES": "total_liabilities",
    "ZCFZL": "debt_ratio",
}


def compare_financials(rows: list[dict]) -> dict:
    warnings = []
    changes = {}
    if rows:
        latest = rows[0]
        previous = next(
            (
                r
                for r in rows[1:]
                if r["end_date"]
                == str(int(latest["end_date"][:4]) - 1) + latest["end_date"][4:]
            ),
            None,
        )
        if previous:
            for key in ("net_profit", "operating_cashflow", "inventory", "receivables"):
                a, b = latest.get(key), previous.get(key)
                changes[key] = (
                    None if a is None or b is None or b == 0 else (a - b) / abs(b) * 100
                )
            if (
                (changes.get("net_profit") or 0) > 20
                and changes.get("operating_cashflow") is not None
                and changes["operating_cashflow"] <= 0
            ):
                warnings.append("净利润增长明显，但经营现金流未同步改善。")
            for key, label in (("inventory", "存货"), ("receivables", "应收账款")):
                if (changes.get(key) or 0) > 30:
                    warnings.append(label + "较上年同期增长超过30%。")
    return {
        "rows": rows,
        "yoy_changes": changes,
        "warnings": warnings,
        "note": "累计报表只比较上年同报告期；负基数使用绝对值，不能当作常规增长率。"
        if rows
        else "数据不足，无法判断。",
    }


class FundamentalProvider:
    def fetch(self, code: str) -> dict:
        merged = {}
        errors = []
        now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")

        def consume(frame: pd.DataFrame, mapping: dict, source: str) -> None:
            for raw in clean(frame.to_dict("records")):
                period = str(raw.get("end_date") or raw.get("REPORT_DATE") or "")[:10]
                if len(period) == 8:
                    period = f"{period[:4]}-{period[4:6]}-{period[6:8]}"
                if not period:
                    continue
                announcement = str(
                    raw.get("f_ann_date")
                    or raw.get("ann_date")
                    or raw.get("NOTICE_DATE")
                    or ""
                )[:10]
                if len(announcement) == 8:
                    announcement = (
                        f"{announcement[:4]}-{announcement[4:6]}-{announcement[6:8]}"
                    )
                if announcement and announcement > now:
                    continue
                row = merged.setdefault(period, {"end_date": period, "source": source})
                if announcement:
                    row["announcement_date"] = max(
                        announcement, row.get("announcement_date", "")
                    )
                for key, target in mapping.items():
                    if raw.get(key) is not None and target not in row:
                        row[target] = raw[key]

        if os.getenv("TUSHARE_TOKEN"):
            for name in ("income", "balancesheet", "cashflow", "fina_indicator"):
                try:
                    consume(
                        fetch("tushare_" + name, {"ts_code": code}), TS_MAP, "Tushare"
                    )
                except Exception as exc:
                    errors.append(name + "：" + type(exc).__name__)
        if not merged:
            for name, args in [
                (
                    "stock_financial_analysis_indicator_em",
                    {"symbol": code, "indicator": "按报告期"},
                ),
                ("stock_balance_sheet_by_report_em", {"symbol": code[-2:] + code[:6]}),
                (
                    "stock_cash_flow_sheet_by_report_em",
                    {"symbol": code[-2:] + code[:6]},
                ),
            ]:
                try:
                    consume(fetch(name, args), EM_MAP, "AKShare / 东方财富")
                except Exception as exc:
                    errors.append(name + "：" + type(exc).__name__)
        rows = sorted(merged.values(), key=lambda r: r["end_date"], reverse=True)[:12]
        for row in rows:
            for key in set(TS_MAP.values()):
                row.setdefault(key, None)
            if (
                row["debt_ratio"] is None
                and row["total_assets"]
                and row["total_liabilities"] is not None
            ):
                row["debt_ratio"] = row["total_liabilities"] / row["total_assets"] * 100
        return {**compare_financials(rows), "errors": errors}
