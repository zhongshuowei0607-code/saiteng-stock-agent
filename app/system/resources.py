from pathlib import Path
import os
import shutil
import time
import psutil


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def resource_snapshot(root: Path) -> dict:
    process = psutil.Process(os.getpid())
    usage = shutil.disk_usage(root)
    database = root / "data/stock_agent.db"
    return {"process_memory_mb": round(process.memory_info().rss / 1024 / 1024, 1), "process_cpu_percent": process.cpu_percent(interval=0.0), "database_size_bytes": database.stat().st_size if database.exists() else 0, "logs_size_bytes": directory_size(root / "logs"), "reports_size_bytes": directory_size(root / "reports"), "disk_total_bytes": usage.total, "disk_free_bytes": usage.free, "measured_at": time.time()}
