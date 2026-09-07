from datetime import date
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from app.data.market_provider import normalize_code
from app.database.repository import clean
from app.indicators.technical import calculate
from app.portfolio.portfolio_service import load_position
from app.system.resources import resource_snapshot

router = APIRouter()


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
    return request.app.state.runner.status()


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
