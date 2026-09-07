"""macOS 一键启动：准备环境、复用已有服务、就绪后打开浏览器。"""
from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000"
TITLE = "赛腾股份每日分析 Agent"


def service_state() -> str:
    """区分本应用、空闲端口和其他服务，避免双开或误打开别的应用。"""
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=1):
            pass
    except OSError:
        return "free"
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL + "/openapi.json", timeout=2) as response:
            data = json.load(response)
        return "ours" if data.get("info", {}).get("title") == TITLE else "other"
    except (OSError, ValueError):
        return "other"


def prepare_environment() -> Path:
    python = ROOT / ".venv/bin/python"
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        print("正在准备项目虚拟环境…", flush=True)
        environment = ROOT / ".venv"
        if environment.exists():
            backup = ROOT / (".venv.backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
            environment.rename(backup)
            print(f"旧环境已保留为 {backup.name}", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        return python
    modules = (
        "fastapi", "uvicorn", "pandas", "numpy", "akshare", "tushare",
        "sqlalchemy", "apscheduler", "httpx", "requests", "jinja2",
        "markdown", "yaml", "dotenv", "pydantic", "pypdf", "tzdata",
    )
    if any(importlib.util.find_spec(module) is None for module in modules):
        print("首次运行：正在安装项目依赖，需要网络连接…", flush=True)
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")],
            check=True,
        )
    return python


def main() -> int:
    state = service_state()
    if state == "ours":
        print("服务已经运行，正在打开 Dashboard。", flush=True)
        subprocess.run(["/usr/bin/open", URL], check=True)
        return 0
    if state == "other":
        print("端口 8000 已被其他服务占用，请先关闭该服务后重试。", flush=True)
        return 1

    python = prepare_environment()
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        # 新建环境后用该环境重新检查依赖，不依赖系统 Python 中的包。
        return subprocess.call([str(python), str(Path(__file__).resolve())], cwd=ROOT)
    env = ROOT / ".env"
    if not env.exists():
        with env.open("x", encoding="utf-8") as destination:
            destination.write((ROOT / ".env.example").read_text(encoding="utf-8"))
    print("正在启动赛腾股份分析工具…", flush=True)
    server = subprocess.Popen([str(python), "run.py"], cwd=ROOT)
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            if server.poll() is not None:
                return server.returncode or 1
            if service_state() == "ours":
                print("服务已就绪。请保留终端窗口；按 Control+C 停止服务。", flush=True)
                subprocess.run(["/usr/bin/open", URL], check=True)
                return server.wait()
            time.sleep(0.5)
        print("服务启动超过 45 秒，请查看终端错误与 logs 日志。", flush=True)
        return 1
    except KeyboardInterrupt:
        print("\n正在停止服务…", flush=True)
        return 0
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
