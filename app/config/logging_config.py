from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import logging


class DailyFileHandler(logging.FileHandler):
    """长驻 Web 跨零点时也按上海日期切换日志文件。"""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(self.filename(), encoding="utf-8")

    def filename(self) -> Path:
        return (
            self.directory
            / f"stock_agent_{datetime.now(ZoneInfo('Asia/Shanghai')):%Y%m%d}.log"
        )

    def emit(self, record: logging.LogRecord) -> None:
        filename = str(self.filename().resolve())
        if self.baseFilename != filename:
            if self.stream:
                self.stream.close()
            self.baseFilename = filename
            self.stream = self._open()
        super().emit(record)


def configure_logging(root: Path) -> None:
    directory = root / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if any(
        isinstance(h, DailyFileHandler) and h.directory == directory
        for h in logger.handlers
    ):
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handler = DailyFileHandler(directory)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if not any(type(h) is logging.StreamHandler for h in logger.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
