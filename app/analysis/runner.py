import logging
import time
from datetime import datetime
from threading import Lock
from zoneinfo import ZoneInfo
from .stock_analyzer import StockAnalyzer


class AnalysisRunner:
    """同一服务实例只允许一个分析任务，手动与调度入口共用。"""

    def __init__(self, analyzer: StockAnalyzer, notifier=None) -> None:
        self.analyzer = analyzer
        self.lock = Lock()
        self.running = False
        self.last_error = None
        self.stage = "idle"
        self.message = "等待分析"
        self.started_at = None
        self.finished_at = None
        self.started_monotonic = None
        self.notifier = notifier

    def reserve(self) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.last_error = None
            self.stage = "queued"
            self.message = "分析任务已排队"
            self.started_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
            self.finished_at = None
            self.started_monotonic = time.monotonic()
            return True

    def progress(self, stage: str, message: str) -> None:
        with self.lock:
            self.stage = stage
            self.message = message

    def run_reserved(self, code: str = "603283.SH") -> None:
        try:
            report = self.analyzer.analyze(code, progress=self.progress)
            if self.notifier:
                if hasattr(self.notifier, "action_alert"):
                    self.notifier.action_alert(report)
                if hasattr(self.notifier, "daily"):
                    self.notifier.daily(report)
            self.progress("complete", "分析完成，日报已更新")
        except Exception as exc:
            logging.error("分析任务失败：%s", type(exc).__name__)
            self.last_error = type(exc).__name__
            self.progress("error", f"分析失败：{type(exc).__name__}")
        finally:
            with self.lock:
                self.running = False
                self.finished_at = datetime.now(
                    ZoneInfo("Asia/Shanghai")
                ).isoformat()

    def status(self) -> dict:
        with self.lock:
            elapsed = (
                round(time.monotonic() - self.started_monotonic, 1)
                if self.running and self.started_monotonic is not None
                else None
            )
            return {
                "running": self.running,
                "stage": self.stage,
                "message": self.message,
                "elapsed_seconds": elapsed,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "error": self.last_error,
            }
