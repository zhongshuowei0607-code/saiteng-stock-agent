from datetime import date, datetime
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import json
import os
import yaml
from fastapi.responses import FileResponse
from app.data.market_provider import normalize_code
from app.database.repository import clean
from app.indicators.technical import calculate
from app.portfolio.portfolio_service import load_position
from app.portfolio.position import Buy, Position
from app.analysis.risk_analyzer import risk_score
from app.analysis.daily_report import render_reports
from app.analysis.action_context import current_action_report
from app.system.resources import resource_snapshot
import time
from sqlalchemy import text

router = APIRouter()


class SetupPayload(BaseModel):
    tushare_token: str = ""
    llm_provider: str = "disabled"
    llm_model: str = "deepseek-chat"
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    ollama_url: str = ""
    bark_enabled: bool = False
    bark_device_key: str = ""
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_use_ssl: bool = True
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    web_username: str = "admin"
    web_password: str = ""
    max_shares: int = Field(default=1000, gt=0)
    buys: list[Buy] = Field(
        default_factory=lambda: [
            Buy(price=50, shares=200),
            Buy(price=48, shares=200),
        ]
    )
    sells: list[Buy] = Field(default_factory=list)
    monitor_interval: int = Field(default=180, ge=60, le=3600)
    risk_warning: int = Field(default=65, ge=0, le=100)
    risk_critical: int = Field(default=85, ge=0, le=100)
    stabilization_threshold: int = Field(default=7, ge=0, le=10)


def _position_payload(payload: SetupPayload) -> dict:
    return {
        "code": "603283.SH",
        "max_shares": payload.max_shares,
        "buys": [
            {"price": float(item.price), "shares": item.shares}
            for item in payload.buys
        ],
        "sells": [
            {"price": float(item.price), "shares": item.shares}
            for item in payload.sells
        ],
    }


def _refresh_latest_portfolio(request: Request, position_payload: dict) -> dict | None:
    repository = request.app.state.repository
    reports = repository.reports(limit=1)
    if not reports:
        return None
    report = reports[0]
    frame = repository.history(report["stock"]["code"])
    price = report.get("market", {}).get("close")
    if price is None and not frame.empty:
        price = float(frame.iloc[-1]["close"])
    position = Position.model_validate(position_payload)
    valuation = position.valuation(price)
    report["portfolio"] = valuation
    monitor = getattr(request.app.state, "monitor", None)
    if monitor is not None:
        monitor.latest_report = None
    report["risk"] = risk_score(report)
    report["portfolio_updated_at"] = datetime.now(
        ZoneInfo("Asia/Shanghai")
    ).isoformat()
    if report.get("ai", {}).get("status") == "generated":
        report["ai"]["portfolio_stale"] = True
    report["decision"] = current_action_report(request.app.state.settings, report)["decision"]
    render_reports(report, request.app.state.settings.path("reports"))
    repository.save_report(report["stock"]["code"], report["date"], report)
    return valuation


@router.post("/api/setup")
def save_setup(payload: SetupPayload, request: Request) -> dict:
    if payload.llm_provider not in ("disabled", "openai", "deepseek", "ollama"):
        raise HTTPException(400, "LLM Provider 无效")
    store = request.app.state.secure_settings
    mapping = {"TUSHARE_TOKEN": payload.tushare_token, "LLM_PROVIDER": payload.llm_provider, "LLM_MODEL": payload.llm_model, "DEEPSEEK_API_KEY": payload.deepseek_api_key, "OPENAI_API_KEY": payload.openai_api_key, "OLLAMA_URL": payload.ollama_url, "BARK_ENABLED": payload.bark_enabled, "BARK_DEVICE_KEY": payload.bark_device_key, "EMAIL_ENABLED": payload.email_enabled, "SMTP_HOST": payload.smtp_host, "SMTP_PORT": payload.smtp_port, "SMTP_USE_SSL": payload.smtp_use_ssl, "SMTP_USER": payload.smtp_user, "SMTP_PASSWORD": payload.smtp_password, "SMTP_FROM": payload.smtp_from, "SMTP_TO": payload.smtp_to, "WEB_USERNAME": payload.web_username}
    for key, value in mapping.items():
        if value not in ("", None) or key.endswith("ENABLED"):
            store.set(key, value)
    if payload.web_password and len(payload.web_password) < 10:
        raise HTTPException(400, "Dashboard 密码至少 10 位")
    if payload.web_password:
        store.set_password(payload.web_password)
    elif not store.is_complete():
        raise HTTPException(400, "首次设置必须填写至少 10 位 Dashboard 密码")
    position = _position_payload(payload)
    request.app.state.settings.path("data/portfolio.json").write_text(json.dumps(position, ensure_ascii=False, indent=2), encoding="utf-8")
    valuation = _refresh_latest_portfolio(request, position)
    request.app.state.settings.config["monitor"]["interval_seconds"] = payload.monitor_interval
    request.app.state.settings.config["risk"] = {"warning_threshold": payload.risk_warning, "critical_threshold": payload.risk_critical}
    store.apply_llm_config(request.app.state.settings.config)
    request.app.state.settings.strategy["confirmation_score"] = payload.stabilization_threshold
    (request.app.state.settings.config_dir / "config.yaml").write_text(yaml.safe_dump(request.app.state.settings.config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (request.app.state.settings.config_dir / "position_strategy.yaml").write_text(yaml.safe_dump(request.app.state.settings.strategy, allow_unicode=True, sort_keys=False), encoding="utf-8")
    store.set("SETUP_COMPLETE", "true")
    store.apply_environment()
    scheduler = request.app.state.scheduler
    if scheduler and scheduler.get_job("realtime_monitor"):
        scheduler.reschedule_job("realtime_monitor", trigger="interval", seconds=payload.monitor_interval)
    return {
        "status": "configured",
        "redirect": "/",
        "portfolio": valuation,
    }


@router.post("/api/notifications/test-bark")
def test_bark(request: Request) -> dict:
    return {"ok": request.app.state.notifier.bark("Stock Agent 测试", "Bark 配置有效", "INFO")}


@router.post("/api/notifications/test-email")
def test_email(request: Request) -> dict:
    return {"ok": request.app.state.notifier.email("Stock Agent 测试", "Email 配置有效")}


def check(code: str) -> str:
    try:
        code = normalize_code(code)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if code != "603283.SH":
        raise HTTPException(404, "当前仅跟踪赛腾股份")
    return code


def latest(request: Request, code: str) -> dict:
    rows = request.app.state.repository.reports(check(code))
    if not rows:
        raise HTTPException(404, "尚未生成日报，请运行分析")
    return rows[0]


@router.get("/api/stock/{code}")
def stock(code: str, request: Request) -> dict:
    return latest(request, code)


@router.get("/api/stock/{code}/history")
def history(code: str, request: Request) -> list[dict]:
    maximum = request.app.state.settings.config.get("monitor", {}).get("max_bars_in_memory", 800)
    return clean(
        request.app.state.repository.history(check(code)).tail(maximum).to_dict("records")
    )


@router.get("/api/stock/{code}/technical")
def technical(code: str, request: Request) -> list[dict]:
    maximum = request.app.state.settings.config.get("monitor", {}).get("max_bars_in_memory", 800)
    return clean(
        calculate(request.app.state.repository.history(check(code)))
        .tail(maximum)
        .to_dict("records")
    )


@router.get("/api/stock/{code}/portfolio")
def portfolio(code: str, request: Request) -> dict:
    check(code)
    frame = request.app.state.repository.history(check(code))
    return load_position(
        request.app.state.settings.path("data/portfolio.json")
    ).valuation(None if frame.empty else float(frame.iloc[-1].close))


@router.get("/api/stock/{code}/report/latest")
def report(code: str, request: Request) -> dict:
    return latest(request, code)


@router.get("/api/reports")
def reports(request: Request) -> list[dict]:
    return [
        {
            "date": r["date"],
            "code": r["stock"]["code"],
            "market_date": r.get("market", {}).get("date"),
            "url": f"/reports/603283/{r['date']}.html",
        }
        for r in request.app.state.repository.reports(limit=100)
    ]


@router.get("/api/system/resources")
def resources(request: Request) -> dict:
    return resource_snapshot(request.app.state.settings.root)


@router.get("/api/health")
def health(request: Request) -> dict:
    app = request.app
    database = "ok"
    try:
        with app.state.repository.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        database = "error"
    reports = app.state.repository.reports(limit=1)
    monitor = app.state.monitor.status()
    resources = resource_snapshot(app.state.settings.root)
    provider = os.getenv("LLM_PROVIDER", app.state.settings.config["llm"]["provider"])
    llm_ready = (
        provider == "ollama" and bool(os.getenv("OLLAMA_URL"))
        or provider == "openai" and bool(os.getenv("OPENAI_API_KEY"))
        or provider == "deepseek" and bool(os.getenv("DEEPSEEK_API_KEY"))
    )
    version_file = app.state.settings.path("VERSION")
    return {"status": "healthy" if database == "ok" else "degraded", "version": version_file.read_text().strip() if version_file.exists() else "1.0.0", "uptime": round(time.monotonic() - app.state.started_at, 1), "database": database, "monitor": monitor, "scheduler": "running" if app.state.scheduler and app.state.scheduler.running else "stopped", "last_market_update": monitor.get("last_market_update"), "last_successful_poll": monitor.get("last_successful_poll"), "last_daily_report": reports[0]["date"] if reports else None, "bark_status": "enabled" if os.getenv("BARK_ENABLED", "false").lower() == "true" else "disabled", "email_status": "enabled" if os.getenv("EMAIL_ENABLED", "false").lower() == "true" else "disabled", "llm_status": "disabled" if provider == "disabled" else "available" if llm_ready else "unavailable", "disk_usage": {"total": resources["disk_total_bytes"], "free": resources["disk_free_bytes"]}, "database_size": resources["database_size_bytes"]}


@router.get("/api/status")
def status(request: Request) -> dict:
    return {"analysis": request.app.state.runner.status(), "monitor": request.app.state.monitor.status() if hasattr(request.app.state, "monitor") else {}}


@router.get("/api/action-guide")
def action_guide(request: Request) -> dict:
    state = request.app.state
    rows = state.repository.reports(limit=1)
    view = current_action_report(state.settings, rows[0] if rows else None, state.monitor)
    notifications = state.notifier.status()
    notifications["last_action_email"] = notifications.get("action")
    notifications["last_daily_email"] = notifications.get("daily")
    return {"decision": view["decision"], "monitor": state.monitor.status(), "notifications": notifications}


@router.get("/api/triggers")
def triggers(request: Request) -> list[dict]:
    return request.app.state.repository.trigger_events()


@router.post("/api/stock/{code}/analyze", status_code=202)
def analyze(code: str, request: Request, background: BackgroundTasks) -> dict:
    code = check(code)
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
        raise HTTPException(403, "只允许当前页面发起分析")
    if not request.app.state.runner.reserve():
        return {"status": "already_running"}
    background.add_task(request.app.state.runner.run_reserved, code)
    return {"status": "running"}


@router.get("/reports/603283/{filename}")
def report_file(filename: str, request: Request) -> FileResponse:
    stem, _, extension = filename.rpartition(".")
    try:
        date.fromisoformat(stem)
    except ValueError:
        raise HTTPException(404, "报告不存在")
    if extension not in ("md", "html") or len(stem) != 10:
        raise HTTPException(404, "报告不存在")
    path = request.app.state.settings.path("reports/603283") / filename
    if not path.is_file():
        raise HTTPException(404, "报告不存在")
    return FileResponse(
        path,
        media_type="text/html" if extension == "html" else "text/markdown",
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"
        },
    )
