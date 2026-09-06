import logging
from threading import Lock
from .stock_analyzer import StockAnalyzer


class AnalysisRunner:
    """同一服务实例只允许一个分析任务，手动与调度入口共用。"""

    def __init__(self, analyzer: StockAnalyzer) -> None:
        self.analyzer = analyzer
        self.lock = Lock()
        self.running = False
        self.last_error = None

    def reserve(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.last_error = None
            return True

    def run_reserved(self, code: str = "603283.SH") -> None:
        try:
            self.analyzer.analyze(code)
        except Exception as exc:
            logging.error("分析任务失败：%s", type(exc).__name__)
            self.last_error = type(exc).__name__
        finally:
            with self.lock:
                self.running = False

    def status(self) -> dict:
        with self.lock:
            return {"running": self.running, "error": self.last_error}
