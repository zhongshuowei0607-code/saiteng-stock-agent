from datetime import datetime
from zoneinfo import ZoneInfo
import logging
import time
from app.config.settings import Settings
from app.database.repository import Repository, clean
from app.data.market_provider import MarketService, normalize_code
from app.data.tushare_provider import TushareProvider
from app.data.akshare_provider import AKShareProvider
from app.indicators.technical import calculate
from app.indicators.support_resistance import levels
from app.indicators.trend import trends
from app.indicators.stabilization import stabilization
from app.portfolio.portfolio_service import load_position, watch_state
from app.llm.factory import make_provider
from app.llm.base import explain
from .risk_analyzer import risk_score
from .daily_report import render_reports

class StockAnalyzer:
    def __init__(self, settings: Settings, repository: Repository):
        self.settings,self.repository=settings,repository
    def analyze(self, code: str = "603283.SH", refresh: bool = True, use_llm: bool = True) -> dict:
        started=time.monotonic(); code=normalize_code(code)
        stock=next((s for s in self.settings.config["stocks"] if s["code"]==code),None)
        if stock is None:
            raise ValueError("第一阶段仅支持配置的赛腾股份")
        date=datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        warnings=[]
        if refresh:
            frame,warnings=MarketService([TushareProvider(),AKShareProvider()],self.repository).update(code)
        else:
            frame=self.repository.history(code)
            warnings.append("本次使用本地缓存，未刷新数据。")
        if len(frame)<250:
            warnings.append(f"仅有{len(frame)}根K线，部分指标数据不足。")
        technical=calculate(frame)
        market={} if frame.empty else clean(frame.iloc[-1].to_dict())
        if market and market["date"]!=date:
            warnings.append("报告生成日与行情日期不同，请按最近实际交易日解读。")
        warnings.append("价格为不复权口径；除权除息可能影响技术信号。")
        position=load_position(self.settings.path("data/portfolio.json"))
        portfolio=position.valuation(market.get("close"))
        stable=stabilization(technical)
        report={"date":date,"generated_at":datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),"stock":stock,"market":market,"technical":{} if technical.empty else clean(technical.iloc[-1].to_dict()),"trend":trends(technical),"portfolio":portfolio,"levels":levels(technical),"stabilization":stable,"news":[],"announcements":[],"industry":{},"fundamental":{},"warnings":warnings}
        if refresh and not frame.empty:
            from app.data.enrichment import enrich
            extra=enrich(code,frame,self.settings.config["peers"],self.repository)
            for key in ("news","announcements","fundamental","industry"):
                report[key]=extra[key]
            warnings.extend(extra["errors"])
            for key in ("fundamental","industry"):
                warnings.extend(report[key].get("errors",[]))
        report["watch_zone"]=watch_state(market.get("close"),stable,self.settings.strategy)
        report["risk"]=risk_score(report)
        previous=self.repository.reports(code,before=date)
        if previous:
            prior=previous[0]
            report["comparison"]={"previous_date":prior["date"],"risk":{"from":prior["risk"]["score"],"to":report["risk"]["score"]},"trend":{"from":prior["trend"],"to":report["trend"]},"state":{"from":prior["watch_zone"]["state"],"to":report["watch_zone"]["state"]},"current_risk_factors":report["risk"]["reasons"]}
        else:
            report["comparison"]={"note":"尚无前一日报，无法比较。"}
        report=clean(report)
        # 提示词只携带抓到的事件；原文在数据库完整保留，模型输入限长。
        prompt_facts={**report}
        for kind in ("news","announcements"):
            prompt_facts[kind]=[{**row,"raw_text":row.get("raw_text", "")[:12000],"prompt_text_truncated":len(row.get("raw_text", ""))>12000} for row in report[kind]]
        report["ai"]=explain(make_provider(self.settings.config["llm"]) if use_llm else None,prompt_facts)
        if any(e.get("stop_adding_observation") for e in report["ai"].get("events",[])):
            report["watch_zone"]=watch_state(market.get("close"),stable,self.settings.strategy,event_stop=True)
        render_reports(report,self.settings.path("reports"))
        self.repository.save_report(code,date,report)
        logging.info("分析完成 code=%s risk=%s duration=%.2fs",code,report["risk"]["score"],time.monotonic()-started)
        return report
