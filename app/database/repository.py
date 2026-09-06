import json
import hashlib
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine
from .models import MarketBar, Report, Document, Fundamental

def clean(value: object) -> object:
    # pandas 统一将 NaN 转成 JSON null，禁止把缺失值误写成零。
    return json.loads(pd.Series([value]).to_json(orient="values", date_format="iso"))[0]

class Repository:
    def __init__(self, engine: Engine):
        self.engine = engine
    def save_bars(self, code: str, frame: pd.DataFrame) -> None:
        with Session(self.engine) as session, session.begin():
            for row in frame.to_dict("records"):
                session.merge(MarketBar(code=code, date=str(row["date"]), payload=clean(row)))
    def history(self, code: str) -> pd.DataFrame:
        with Session(self.engine) as session:
            rows = session.scalars(select(MarketBar).where(MarketBar.code == code).order_by(MarketBar.date)).all()
            return pd.DataFrame([r.payload for r in rows])
    def save_report(self, code: str, date: str, payload: dict) -> None:
        with Session(self.engine) as session, session.begin():
            session.merge(Report(code=code, date=date, payload=clean(payload)))
    def reports(self, code: str = "603283.SH", before: str | None = None) -> list[dict]:
        query = select(Report).where(Report.code == code)
        if before:
            query = query.where(Report.date < before)
        with Session(self.engine) as session:
            return [r.payload for r in session.scalars(query.order_by(Report.date.desc())).all()]
    def save_documents(self, code: str, kind: str, rows: list[dict]) -> None:
        with Session(self.engine) as session, session.begin():
            for row in rows:
                key = hashlib.sha256((code + kind + row.get("url", "") + row.get("title", "") + row.get("date", "")).encode()).hexdigest()
                session.merge(Document(id=key, code=code, kind=kind, payload=clean(row)))
    def save_fundamentals(self, code: str, rows: list[dict]) -> None:
        with Session(self.engine) as session, session.begin():
            for row in rows:
                session.merge(Fundamental(code=code, date=row["end_date"], payload=clean(row)))
