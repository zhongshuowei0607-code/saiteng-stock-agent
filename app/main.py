from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
from starlette.responses import Response
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
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
from app.config.secure_store import SecureSettings
from app.security import authenticate
from app.notifications import NotificationService
from app.monitor import RealtimeMonitor
from app.monitor.triggers import TriggerEngine
from app.scheduler.jobs import TradingCalendar


def create_app(
    settings: Settings | None = None, repository: Repository | None = None
) -> FastAPI:
    settings = settings or load_settings()
    from app.config.logging_config import configure_logging

    configure_logging(settings.root)
    repository = repository or Repository(
        create_db(settings.path("data/stock_agent.db"))
    )
    analyzer = StockAnalyzer(settings, repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 无报告时先建立缺失/缓存报告，保证首页即时可用。
        if not repository.reports():
            analyzer.analyze(refresh=False, use_llm=False)
        scheduler = None
        if settings.config["scheduler"].get("enabled", True):
            from app.scheduler.jobs import TradingCalendar, build_scheduler

            scheduler = build_scheduler(
                app.state.runner,
                TradingCalendar(settings.path("data/trading_calendar.json")),
                settings.config["scheduler"],
                app.state.monitor,
                repository,
            )
            scheduler.start()
            app.state.scheduler = scheduler
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        repository.engine.dispose()

    app = FastAPI(title="赛腾股份每日分析 Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.repository = repository
    app.state.notifier = NotificationService(settings.root)
    app.state.runner = AnalysisRunner(analyzer, app.state.notifier)
    app.state.calendar = TradingCalendar(settings.path("data/trading_calendar.json"))
    app.state.monitor = RealtimeMonitor(settings, repository, analyzer, app.state.calendar, TriggerEngine(repository, app.state.notifier, settings.config["monitor"]["cooldown_minutes"]))
    app.state.secure_settings = SecureSettings(repository.engine, settings.root)
    app.state.started_at = time.monotonic()
    app.state.scheduler = None
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def log_request(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        denied = authenticate(request)
        if denied is not None:
            return denied
        started = time.monotonic()
        response = await call_next(request)
        logging.info(
            "HTTP %s %s %s %.3fs",
            request.method,
            request.url.path,
            response.status_code,
            time.monotonic() - started,
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.include_router(router)
    app.mount(
        "/static", StaticFiles(directory=settings.path("app/web/static")), name="static"
    )
    templates = Jinja2Templates(directory=settings.path("app/web/templates"))

    @app.get("/setup")
    def setup_page(request: Request) -> Response:
        store = app.state.secure_settings
        return templates.TemplateResponse(request=request, name="setup.html", context={"editing": store.is_complete(), "masked": store.masked})

    @app.get("/settings")
    def settings_page(request: Request) -> Response:
        return templates.TemplateResponse(request=request, name="setup.html", context={"editing": True, "masked": app.state.secure_settings.masked})

    @app.get("/")
    def dashboard(request: Request) -> Response:
        rows = repository.reports(limit=30)
        report = rows[0] if rows else None
        portfolio = (
            report["portfolio"]
            if report
            else load_position(settings.path("data/portfolio.json")).valuation(None)
        )
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"r": report, "p": portfolio, "reports": rows[:30]},
        )

    return app
