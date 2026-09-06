from contextlib import asynccontextmanager
import logging
import time
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.config.settings import Settings, load_settings
from app.database.db import create_db
from app.database.repository import Repository
from app.analysis.stock_analyzer import StockAnalyzer
from app.analysis.runner import AnalysisRunner
from app.portfolio.portfolio_service import load_position
from app.api.routes import router

def create_app(settings: Settings | None = None, repository: Repository | None = None) -> FastAPI:
    settings=settings or load_settings()
    repository=repository or Repository(create_db(settings.path("data/stock_agent.db")))
    analyzer=StockAnalyzer(settings,repository)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 无报告时先建立缺失/缓存报告，保证首页即时可用。
        if not repository.reports():
            analyzer.analyze(refresh=False,use_llm=False)
        yield
    app=FastAPI(title="赛腾股份每日分析 Agent",lifespan=lifespan)
    app.state.settings=settings;app.state.repository=repository
    app.state.runner=AnalysisRunner(analyzer)
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=["localhost","127.0.0.1","[::1]","testserver"])
    @app.middleware("http")
    async def log_request(request: Request, call_next):
        started=time.monotonic();response=await call_next(request)
        logging.info("HTTP %s %s %s %.3fs",request.method,request.url.path,response.status_code,time.monotonic()-started)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        return response
    app.include_router(router)
    app.mount("/static",StaticFiles(directory=settings.path("app/web/static")),name="static")
    templates=Jinja2Templates(directory=settings.path("app/web/templates"))
    @app.get("/")
    def dashboard(request: Request):
        rows=repository.reports();report=rows[0] if rows else None
        portfolio=report["portfolio"] if report else load_position(settings.path("data/portfolio.json")).valuation(None)
        return templates.TemplateResponse(request=request,name="dashboard.html",context={"r":report,"p":portfolio,"reports":rows[:30]})
    return app
