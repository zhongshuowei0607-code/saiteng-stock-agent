from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
from starlette.responses import Response
import logging
import os
from pathlib import Path
import json
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
from app.analysis.action_context import current_action_report
from app.analysis.walkforward_shadow import load_shadow, summarize_shadow
from app.portfolio.portfolio_service import load_position
from app.portfolio.position import DEFAULT_MAX_SHARES
from app.api.routes import router
from app.config.secure_store import create_secure_settings
from app.security import authenticate
from app.notifications import NotificationService
from app.monitor import RealtimeMonitor
from app.monitor.triggers import TriggerEngine
from app.scheduler.jobs import TradingCalendar
from app.database.migrations import migrate


def create_app(
    settings: Settings | None = None, repository: Repository | None = None
) -> FastAPI:
    settings = settings or load_settings()
    from app.config.logging_config import configure_logging

    configure_logging(settings.root)
    secure_settings = create_secure_settings(settings.root)
    secure_settings.apply_llm_config(settings.config)
    repository = repository or Repository(
        create_db(settings.path("data/stock_agent.db"))
    )
    analyzer = StockAnalyzer(settings, repository)
    version_file = settings.path("VERSION")
    if not version_file.exists():
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
    version = version_file.read_text().strip()
    migrate(repository.engine, version_file)

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
                settings.root,
                settings.config.get("storage", {}),
            )
            scheduler.start()
            app.state.scheduler = scheduler
        yield
        if scheduler:
            scheduler.shutdown(wait=False)
        repository.engine.dispose()
        app.state.secure_settings.engine.dispose()

    app = FastAPI(title="赛腾股份每日分析 Agent", lifespan=lifespan)
    app.state.settings = settings
    app.state.repository = repository
    app.state.notifier = NotificationService(settings.root)
    app.state.runner = AnalysisRunner(analyzer, app.state.notifier)
    app.state.calendar = TradingCalendar(settings.path("data/trading_calendar.json"))
    app.state.monitor = RealtimeMonitor(settings, repository, analyzer, app.state.calendar, TriggerEngine(repository, app.state.notifier, settings.config["monitor"]["cooldown_minutes"]))
    app.state.secure_settings = secure_settings
    app.state.started_at = time.monotonic()
    app.state.scheduler = None
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[item.strip() for item in os.getenv("ALLOWED_HOSTS", "*").split(",")],
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

    def setup_context(store, editing: bool) -> dict:
        portfolio_file = settings.path("data/portfolio.json")
        portfolio = (
            json.loads(portfolio_file.read_text(encoding="utf-8"))
            if portfolio_file.exists()
            else {
                "max_shares": DEFAULT_MAX_SHARES,
                "account_equity": None,
                "cash": None,
                "available_shares": None,
                "risk_per_trade_pct": 1.0,
                "atr_stop_multiplier": 2.0,
                "buys": [],
                "sells": [],
            }
        )
        portfolio.setdefault("max_shares", DEFAULT_MAX_SHARES)
        portfolio.setdefault("account_equity", None)
        portfolio.setdefault("cash", None)
        portfolio.setdefault("available_shares", None)
        portfolio.setdefault("risk_per_trade_pct", 1.0)
        portfolio.setdefault("atr_stop_multiplier", 2.0)
        portfolio.setdefault("buys", [])
        portfolio.setdefault("sells", [])
        values = {
            key: store.get(key, "")
            for key in (
                "BARK_ENABLED",
                "EMAIL_ENABLED",
                "SMTP_HOST",
                "SMTP_PORT",
                "SMTP_USER",
                "SMTP_FROM",
                "SMTP_TO",
                "WEB_USERNAME",
            )
        }
        return {
            "editing": editing,
            "masked": store.masked,
            "config": settings.config,
            "strategy": settings.strategy,
            "portfolio": portfolio,
            "values": values,
        }

    @app.get("/setup")
    def setup_page(request: Request) -> Response:
        store = app.state.secure_settings
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context=setup_context(store, store.is_complete()),
        )

    @app.get("/settings")
    def settings_page(request: Request) -> Response:
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context=setup_context(app.state.secure_settings, True),
        )

    @app.get("/")
    def dashboard(request: Request) -> Response:
        rows = repository.reports(limit=30)
        report = rows[0] if rows else None
        if report:
            report = current_action_report(settings, report, app.state.monitor)
        if report:
            for key in ("close", "pct_change"):
                report.setdefault("market", {}).setdefault(key, None)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        price = report.get("market", {}).get("close") if report else None
        portfolio = load_position(
            settings.path("data/portfolio.json")
        ).valuation(price)
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"r": report, "p": portfolio, "shadow": summarize_shadow(load_shadow(settings.root)), "reports": rows[:30], "version": version, "triggers": [item for item in repository.trigger_events(50) if item["created_at"].startswith(today)][:20]},
        )

    return app
