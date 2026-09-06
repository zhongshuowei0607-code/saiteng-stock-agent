"""隔离第三方抓取：父进程可强制终止超时请求，兼容 Windows spawn。"""

import json
import sys


def main() -> None:
    request = json.loads(sys.stdin.read())
    name = request["name"]
    args = request["args"]
    allowed = {
        "stock_news_em",
        "stock_zh_a_disclosure_report_cninfo",
        "stock_financial_analysis_indicator_em",
        "stock_balance_sheet_by_report_em",
        "stock_cash_flow_sheet_by_report_em",
        "tool_trade_date_hist_sina",
    }
    if name in ("tushare_history", "akshare_history"):
        from .tushare_provider import TushareProvider
        from .akshare_provider import AKShareProvider

        frame = (
            TushareProvider() if name == "tushare_history" else AKShareProvider()
        ).history(**args)
    elif name.startswith("tushare_") and name[8:] in (
        "income",
        "balancesheet",
        "cashflow",
        "fina_indicator",
        "trade_cal",
        "moneyflow",
    ):
        from .tushare_provider import TushareProvider

        frame = getattr(TushareProvider().client(), name[8:])(**args)
    elif name in allowed:
        import akshare as ak

        frame = getattr(ak, name)(**args)
    else:
        raise ValueError("不允许的数据接口")
    print(
        "RESULT_JSON:"
        + frame.to_json(orient="records", date_format="iso", force_ascii=False)
    )


if __name__ == "__main__":
    main()
