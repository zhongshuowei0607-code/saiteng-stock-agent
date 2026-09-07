from datetime import date
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
import json
from fastapi.responses import FileResponse
from app.data.market_provider import normalize_code
from app.database.repository import clean
from app.indicators.technical import calculate
from app.portfolio.portfolio_service import load_position
from app.system.resources import resource_snapshot

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
    web_password: str = Field(min_length=10)
    max_shares: int = Field(default=1000, gt=0)
    buys: list[dict] = Field(default_factory=lambda: [{"price": 50, "shares": 200}, {"price": 48, "shares": 200}])
    sells: list[dict] = Field(default_factory=list)


@router.post("/api/setup")
def save_setup(payload: SetupPayload, request: Request) -> dict:
    if payload.llm_provider not in ("disabled", "openai", "deepseek", "ollama"):
        raise HTTPException(400, "LLM Provider 无效")
    store = request.app.state.secure_settings
    mapping = {"TUSHARE_TOKEN": payload.tushare_token, "LLM_PROVIDER": payload.llm_provider, "LLM_MODEL": payload.llm_model, "DEEPSEEK_API_KEY": payload.deepseek_api_key, "OPENAI_API_KEY": payload.openai_api_key, "OLLAMA_URL": payload.ollama_url, "BARK_ENABLED": payload.bark_enabled, "BARK_DEVICE_KEY": payload.bark_device_key, "EMAIL_ENABLED": payload.email_enabled, "SMTP_HOST": payload.smtp_host, "SMTP_PORT": payload.smtp_port, "SMTP_USE_SSL": payload.smtp_use_ssl, "SMTP_USER": payload.smtp_user, "SMTP_PASSWORD": payload.smtp_password, "SMTP_FROM": payload.smtp_from, "SMTP_TO": payload.smtp_to, "WEB_USERNAME": payload.web_username}
    for key, value in mapping.items():
        if value not in ("", None) or key.endswith("ENABLED"):
            store.set(key, value)
    store.set_password(payload.web_password)
    position = {"code": "603283.SH", "max_shares": payload.max_shares, "buys": payload.buys, "sells": payload.sells}
    request.app.state.settings.path("data/portfolio.json").write_text(json.dumps(position, ensure_ascii=False, indent=2), encoding="utf-8")
    store.set("SETUP_COMPLETE", "true")
    store.apply_environment()
    return {"status": "configured", "redirect": "/"}


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


@router.get("/api/status")
def status(request: Request) -> dict:
    return {"analysis": request.app.state.runner.status(), "monitor": request.app.state.monitor.status() if hasattr(request.app.state, "monitor") else {}}


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
        raise HTTPException(409, "分析正在运行，请稍候")
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
