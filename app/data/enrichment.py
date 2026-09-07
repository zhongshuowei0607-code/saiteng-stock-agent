from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import pandas as pd
from app.database.repository import Repository
from .news_provider import EastmoneyNewsProvider
from .announcement_provider import AnnouncementProvider
from .fundamental_provider import FundamentalProvider
from .industry_provider import IndustryProvider
from .moneyflow_provider import moneyflow


def enrich(code: str, frame: pd.DataFrame, peers: dict, repository: Repository) -> dict:
    values = {
        "news": [],
        "announcements": [],
        "fundamental": {},
        "industry": {},
        "errors": [],
        "moneyflow": {},
    }
    jobs = {
        "moneyflow": lambda: moneyflow(code, str(frame.iloc[-1]["date"])),
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
