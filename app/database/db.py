from pathlib import Path
from typing import Any
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from .models import Base


def create_db(path: Path) -> Engine:
    engine = create_engine(
        "sqlite:///" + str(path),
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure(connection: Any, record: Any) -> None:
        connection.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(engine)
    return engine
