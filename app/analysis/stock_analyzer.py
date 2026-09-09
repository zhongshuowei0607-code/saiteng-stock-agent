from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import time
from collections.abc import Callable
from app.config.settings import Settings
from app.database.repository import Repository, clean
from app.data.market_provider import MarketService, normalize_code
from app.indicators.technical import calculate
from app.indicators.support_resistance import levels
from app.indicators.trend import trends
from app.indicators.stabilization import stabilization
from app.portfolio.portfolio_service import load_position, watch_state
from app.llm.factory import make_provider
from app.llm.base import explain
from .risk_analyzer import risk_score
from .daily_report import render_reports
from .locking import analysis_lock
from .comparison import compare
from app.data.remote_market import providers


class StockAnalyzer:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings, self.repository = settings, repository

    def analyze(
        self,
        code: str = "603283.SH",
        refresh: bool = True,
        use_llm: bool = True,
        progress: Callable[[str, str], None] | None = None,
    ) -> dict:
        with analysis_lock(self.settings.path("data/analysis.lock")):
            return self._analyze(code, refresh, use_llm, progress)

    def _analyze(
        self,
        code: str,
        refresh: bool,
        use_llm: bool,
        progress: Callable[[str, str], None] | None,
    ) -> dict:
        def update(stage: str, message: str) -> None:
            if progress:
                progress(stage, message)

        started = time.monotonic()
        update("preparing", "准备分析数据")
        code = normalize_code(code)
        stock = next(
            (s for s in self.settings.config["stocks"] if s["code"] == code), None
        )
        if stock is None:
            raise ValueError("第一阶段仅支持配置的赛腾股份")
        date = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        warnings = []
        if refresh:
            update("market", "更新行情数据")
            frame, warnings = MarketService(providers(), self.repository).update(
                code, self.settings.config["market"]["history_days"]
            )
        else:
            frame = self.repository.history(code)
            warnings.append("本次使用本地缓存，未刷新数据。")
        if len(frame) < self.settings.config["market"]["minimum_bars"]:
            warnings.append(f"仅有{len(frame)}根K线，部分指标数据不足。")
        technical = calculate(frame)
        update("indicators", "计算技术指标和风险评分")
        market = {} if frame.empty else clean(frame.iloc[-1].to_dict())
        if market and market["date"] != date:
            warnings.append("报告生成日与行情日期不同，请按最近实际交易日解读。")
        warnings.append("价格为不复权口径；除权除息可能影响技术信号。")
        position = load_position(self.settings.path("data/portfolio.json"))
        portfolio = position.valuation(market.get("close"))
        stable = stabilization(technical)
        report = {
            "date": date,
            "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "stock": stock,
            "market": market,
            "technical": {} if technical.empty else clean(technical.iloc[-1].to_dict()),
            "trend": trends(technical),
            "portfolio": portfolio,
            "levels": levels(technical),
            "stabilization": stable,
            "news": [],
            "announcements": [],
            "industry": {},
            "moneyflow": {},
            "fundamental": {},
            "warnings": warnings,
            "stale_data": not market or market.get("date") != date,
        }
        if refresh and not frame.empty:
            update("sources", "更新财务、公告、新闻和行业数据")
            from app.data.enrichment import enrich

            extra = enrich(code, frame, self.settings.config["peers"], self.repository)
            for key in (
                "news",
                "announcements",
                "fundamental",
                "industry",
                "moneyflow",
            ):
                report[key] = extra[key]
            warnings.extend(extra["errors"])
            for key in ("fundamental", "industry"):
                warnings.extend(report[key].get("errors", []))
        if not refresh:
            cached = self.repository.reports(code)
            if cached:
                for key in (
                    "news",
                    "announcements",
                    "fundamental",
                    "industry",
                    "moneyflow",
                ):
                    report[key] = cached[0].get(
                        key, [] if key in ("news", "announcements") else {}
                    )
                warnings.append("新闻/财务/同行使用前次日报缓存，未刷新。")
        # 突破要求连续两日收于此前20日高点上方，且当日放量。
        breakout = False
        if len(technical) >= 23:
            boundary = float(technical.high.iloc[-22:-2].max())
            breakout = bool(
                (technical.close.iloc[-2:] > boundary).all()
                and technical.iloc[-1].volume_ratio >= 1.2
            )
        report["watch_zone"] = watch_state(
            market.get("close"),
            stable,
            self.settings.strategy,
            {"breakout_confirmed": breakout},
        )
        report["risk"] = risk_score(report)
        previous = next(
            (
                r
                for r in self.repository.reports(code, before=date)
                if r.get("market", {}).get("date")
                and r["market"]["date"] < market.get("date", "")
            ),
            None,
        )
        report["comparison"] = compare(previous, report)
        report = clean(report)
        # 提示词只携带抓到的事件；原文在数据库完整保留，模型输入限长。
        prompt_facts = {**report}
        for kind in ("news", "announcements"):
            prompt_facts[kind] = [
                {
                    **row,
                    "raw_text": row.get("raw_text", "")[:2000],
                    "prompt_text_truncated": len(row.get("raw_text", "")) > 2000,
                }
                for row in report[kind][:4]
            ]
        try:
            update("llm", "等待 AI 生成今日总结")
            provider = make_provider(self.settings.config["llm"]) if use_llm else None
        except Exception as exc:
            logging.warning("模型配置不可用：%s", type(exc).__name__)
            provider = None
        report["ai"] = explain(provider, prompt_facts)
        if any(
            e.get("stop_adding_observation") for e in report["ai"].get("events", [])
        ):
            report["watch_zone"] = watch_state(
                market.get("close"), stable, self.settings.strategy, event_stop=True
            )
        report["comparison"] = compare(previous, report)
        update("report", "生成日报并写入数据库")
        render_reports(report, self.settings.path("reports"))
        self.repository.save_report(code, date, report)
        logging.info(
            "分析完成 code=%s risk=%s duration=%.2fs",
            code,
            report["risk"]["score"],
            time.monotonic() - started,
        )
        return report
