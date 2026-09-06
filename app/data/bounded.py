import json
import os
import subprocess
import sys
from pathlib import Path
import pandas as pd


def fetch(name: str, args: dict, timeout: int = 35) -> pd.DataFrame:
    if name.startswith("tushare_") and not os.getenv("TUSHARE_TOKEN"):
        raise ValueError("未配置 TUSHARE_TOKEN")
    # 仅重试一次第三方进程失败；硬超时直接降级，避免无界等待。
    for attempt in range(2):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "app.data.worker"],
                input=json.dumps({"name": name, "args": args}),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout,
                check=True,
                cwd=Path(__file__).resolve().parents[2],
            )
            marker = "RESULT_JSON:"
            if marker not in result.stdout:
                raise ValueError("数据源没有返回可解析结果")
            return pd.DataFrame(json.loads(result.stdout.rsplit(marker, 1)[1]))
        except subprocess.CalledProcessError:
            if attempt:
                raise
    raise RuntimeError("数据源获取失败")
