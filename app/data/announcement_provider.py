from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from io import BytesIO
from urllib.parse import urlparse, parse_qs
import httpx
from pypdf import PdfReader
from .bounded import fetch
from app.analysis.event_analyzer import classify


def extract_pdf(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in ("static.cninfo.com.cn", "www.cninfo.com.cn"):
        return ""
    if not parsed.path.lower().endswith(".pdf"):
        # 巨潮详情页的公告 id 与时间可映射到官方 PDF 地址。
        query = parse_qs(parsed.query)
        aid = query.get("announcementId", [""])[0]
        date = query.get("announcementTime", [""])[0][:10]
        if not aid.isdigit() or len(date) != 10:
            return ""
        url = f"https://static.cninfo.com.cn/finalpage/{date}/{aid}.PDF"
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 12_000_000:
                    raise ValueError("公告 PDF 超出大小限制")
    reader = PdfReader(BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages[:80])


class AnnouncementProvider:
    def fetch(self, code: str) -> list[dict]:
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        frame = fetch(
            "stock_zh_a_disclosure_report_cninfo",
            {
                "symbol": code[:6],
                "market": "沪深京",
                "start_date": (now - timedelta(days=45)).strftime("%Y%m%d"),
                "end_date": now.strftime("%Y%m%d"),
            },
        )
        rows = []
        if not frame.empty:
            frame = frame.sort_values("公告时间", ascending=False)
        for i, row in enumerate(frame.to_dict("records")[:15]):
            item = {
                "title": str(row.get("公告标题", "")),
                "date": str(row.get("公告时间", "")),
                "source": "巨潮资讯",
                "url": str(row.get("公告链接", "")),
                "raw_text": "",
            }
            if i < 3:
                try:
                    item["raw_text"] = extract_pdf(item["url"])
                except Exception:
                    item["text_status"] = "原文提取失败"
            item["text_status"] = item.get(
                "text_status",
                "已提取（最多80页）" if item["raw_text"] else "原文未获取",
            )
            rows.append(item)
        return classify(rows)
