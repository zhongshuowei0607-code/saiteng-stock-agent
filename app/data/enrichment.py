from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pandas as pd
from app.database.repository import Repository
from .news_provider import EastmoneyNewsProvider
from .announcement_provider import AnnouncementProvider
from .fundamental_provider import FundamentalProvider, compare_financials
from .industry_provider import IndustryProvider
from .moneyflow_provider import moneyflow
from .bounded import fetch


def _source_status(status: str, count: int = 0, date: str | None = None, error: str | None = None) -> dict:
    value = {"status": status, "count": count}
    if date:
        value["date"] = date
    if error:
        value["error"] = error
    return value


def enrich(code: str, frame: pd.DataFrame, peers: dict, repository: Repository) -> dict:
    values = {
        "news": [],
        "announcements": [],
        "fundamental": {},
        "industry": {},
        "quote": {},
        "errors": [],
        "moneyflow": {},
        "source_status": {},
    }
    jobs = {
        "moneyflow": lambda: moneyflow(code, str(frame.iloc[-1]["date"])),
        "quote": lambda: fetch(
            "eastmoney_quote",
            {"code": code, "market_date": str(frame.iloc[-1]["date"])},
        )
        .iloc[-1]
        .to_dict(),
        "news": lambda: EastmoneyNewsProvider().fetch(code),
        "announcements": lambda: AnnouncementProvider().fetch(code),
        "fundamental": lambda: FundamentalProvider().fetch(code),
        "industry": lambda: IndustryProvider(repository).fetch(
            code, {code: "赛腾股份", **peers}, frame
        ),
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                values[name] = future.result()
            except Exception as exc:
                message = name + " 获取失败：" + type(exc).__name__
                logging.warning(message)
                values["errors"].append(message)
                values["source_status"][name] = _source_status(
                    "failed", error=type(exc).__name__
                )

    for kind in ("news", "announcements"):
        rows = values[kind]
        if rows:
            values["source_status"][kind] = _source_status(
                "live",
                count=len(rows),
                date=max((str(row.get("date", "")) for row in rows), default=""),
            )
            continue
        cached = repository.documents(code, kind, limit=20)
        if cached:
            values[kind] = cached
            latest = max((str(row.get("date", "")) for row in cached), default="")
            values["source_status"][kind] = _source_status(
                "cached", count=len(cached), date=latest
            )
            values["errors"].append(
                f"{kind} 实时获取为空，已使用本地最近缓存（{latest or '日期未知'}）。"
            )
        else:
            values["source_status"][kind] = _source_status("empty")

    fundamental = values["fundamental"]
    if fundamental.get("rows"):
        values["source_status"]["fundamental"] = _source_status(
            "live",
            count=len(fundamental["rows"]),
            date=str(fundamental["rows"][0].get("end_date", "")),
        )
    else:
        cached = repository.fundamentals(code, limit=12)
        if cached:
            values["fundamental"] = compare_financials(cached)
            values["fundamental"]["note"] = "实时财务获取为空，使用本地最近报告期缓存。"
            values["source_status"]["fundamental"] = _source_status(
                "cached",
                count=len(cached),
                date=str(cached[0].get("end_date", "")),
            )
            values["errors"].append("financial 实时获取为空，已使用本地财务缓存。")
        else:
            if values["source_status"].get("fundamental", {}).get("status") != "failed":
                values["source_status"]["fundamental"] = _source_status("empty")

    if values["industry"].get("rows"):
        values["source_status"]["industry"] = _source_status(
            "live", count=len(values["industry"]["rows"])
        )
    else:
        if values["source_status"].get("industry", {}).get("status") != "failed":
            values["source_status"]["industry"] = _source_status("empty")
    if values["moneyflow"].get("date"):
        values["source_status"]["moneyflow"] = _source_status(
            "live", date=str(values["moneyflow"]["date"])
        )
    else:
        if values["source_status"].get("moneyflow", {}).get("status") != "failed":
            values["source_status"]["moneyflow"] = _source_status("empty")
    if values["quote"]:
        values["source_status"]["quote"] = _source_status(
            "live",
            count=1,
            date=str(frame.iloc[-1]["date"]),
        )
    else:
        if values["source_status"].get("quote", {}).get("status") != "failed":
            values["source_status"]["quote"] = _source_status("empty")
    # 同行公司新闻作为行业新闻样本，明确不代表完整行业新闻覆盖。
    peer_code = next(iter(peers), None)
    if peer_code:
        try:
            more = EastmoneyNewsProvider().fetch(peer_code)
            for row in more:
                row["scope"] = "同行新闻样本 / " + peers[peer_code]
            values["news"].extend(more[:5])
        except Exception:
            values["errors"].append("同行新闻样本获取失败")
    for kind in ("news", "announcements"):
        repository.save_documents(code, kind, values[kind])
    repository.save_fundamentals(code, values["fundamental"].get("rows", []))
    return values
