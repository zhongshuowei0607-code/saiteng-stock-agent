from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging

LOG_FILES = ("app", "market", "monitor", "notification", "error")


def configure_logging(root: Path) -> None:
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    app_path = (directory / "app.log").resolve()
    if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == app_path for h in logger.handlers):
        handler = RotatingFileHandler(app_path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        errors = RotatingFileHandler(directory / "error.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
        errors.setLevel(logging.ERROR)
        errors.setFormatter(formatter)
        logger.addHandler(errors)
    if not any(type(h) is logging.StreamHandler for h in logger.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    for name in ("market", "monitor", "notification"):
        named = logging.getLogger(name)
        named.setLevel(logging.INFO)
        path = (directory / f"{name}.log").resolve()
        if not any(isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == path for h in named.handlers):
            handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
            handler.setFormatter(formatter)
            named.addHandler(handler)
