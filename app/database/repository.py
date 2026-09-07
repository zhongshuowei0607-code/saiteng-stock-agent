import json
import hashlib
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.engine import Engine
from .models import MarketBar, Report, Document, Fundamental


def clean(value: object) -> object:
    # pandas 统一将 NaN 转成 JSON null，禁止把缺失值误写成零。
    return json.loads(pd.Series([value]).to_json(orient="values", date_format="iso"))[0]


class Repository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_bars(self, code: str, frame: pd.DataFrame) -> None:
        with Session(self.engine) as session, session.begin():
            for row in frame.to_dict("records"):
                session.merge(
                    MarketBar(code=code, date=str(row["date"]), payload=clean(row))
                )

    def history(self, code: str) -> pd.DataFrame:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(MarketBar).where(MarketBar.code == code).order_by(MarketBar.date)
            ).all()
            return pd.DataFrame([r.payload for r in rows])

    def save_report(self, code: str, date: str, payload: dict) -> None:
        with Session(self.engine) as session, session.begin():
            session.merge(Report(code=code, date=date, payload=clean(payload)))

    def reports(self, code: str = "603283.SH", before: str | None = None, limit: int | None = None) -> list[dict]:
        query = select(Report).where(Report.code == code)
        if before:
            query = query.where(Report.date < before)
        query = query.order_by(Report.date.desc())
        if limit:
            query = query.limit(limit)
        with Session(self.engine) as session:
            return [
                r.payload
                for r in session.scalars(query).all()
            ]

    def save_documents(self, code: str, kind: str, rows: list[dict]) -> None:
        with Session(self.engine) as session, session.begin():
            for row in rows:
                key = hashlib.sha256(
                    (
                        code
                        + kind
                        + row.get("url", "")
                        + row.get("title", "")
                        + row.get("date", "")
                    ).encode()
                ).hexdigest()
                session.merge(
                    Document(id=key, code=code, kind=kind, payload=clean(row))
                )

    def save_fundamentals(self, code: str, rows: list[dict]) -> None:
        with Session(self.engine) as session, session.begin():
            for row in rows:
                session.merge(
                    Fundamental(code=code, date=row["end_date"], payload=clean(row))
                )

    def trigger_state(self, signal: str) -> dict | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT signal,state,last_triggered,updated_at FROM trigger_states WHERE signal=:s"), {"s": signal}).mappings().first()
        return dict(row) if row else None

    def save_trigger_state(self, signal: str, state: str, last_triggered: str | None, updated_at: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO trigger_states(signal,state,last_triggered,updated_at) VALUES(:s,:state,:last,:now) ON CONFLICT(signal) DO UPDATE SET state=:state,last_triggered=:last,updated_at=:now"), {"s": signal, "state": state, "last": last_triggered, "now": updated_at})

    def add_trigger_event(self, signal: str, level: str, title: str, message: str, created_at: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO trigger_events(signal,level,title,message,created_at) VALUES(:s,:l,:t,:m,:c)"), {"s": signal, "l": level, "t": title, "m": message, "c": created_at})

    def trigger_events(self, limit: int = 50) -> list[dict]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT signal,level,title,message,created_at FROM trigger_events ORDER BY id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
        return [dict(row) for row in rows]
