from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from .bounded import fetch
from app.analysis.event_analyzer import classify
class NewsProvider(ABC):
    @abstractmethod
    def fetch(self, code: str) -> list[dict]: ...
class EastmoneyNewsProvider(NewsProvider):
    def fetch(self, code: str) -> list[dict]:
        frame=fetch("stock_news_em",{"symbol":code[:6]})
        return classify([{"title":str(row.get("新闻标题","")),"date":str(row.get("发布时间","")),"source":str(row.get("文章来源","东方财富")),"url":str(row.get("新闻链接","")),"raw_text":str(row.get("新闻内容","")),"scope":"公司/个股"} for row in frame.to_dict("records")][:20])
