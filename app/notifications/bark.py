from __future__ import annotations

import logging
import os
import time
from urllib.parse import quote
import httpx

LOGGER = logging.getLogger("notification")


def send_bark(title: str, message: str, level: str = "INFO") -> bool:
    if os.getenv("BARK_ENABLED", "false").lower() != "true":
        return False
    key = os.getenv("BARK_DEVICE_KEY", "")
    if not key:
        LOGGER.warning("Bark 已启用但缺少 Device Key")
        return False
    base = os.getenv("BARK_BASE_URL", "https://api.day.app").rstrip("/")
    sounds = {"INFO": "calypso", "WATCH": "minuet", "WARNING": "alarm", "CRITICAL": "sosumi"}
    payload = {"level": "timeSensitive" if level in ("WARNING", "CRITICAL") else "active", "sound": sounds.get(level, "calypso"), "group": "Stock Agent"}
    for attempt, delay in enumerate((0, 3, 10)):
        if delay:
            time.sleep(delay)
        try:
            response = httpx.post(f"{base}/{quote(key, safe='')}/{quote(title, safe='')}/{quote(message, safe='')}", params=payload, timeout=10)
            response.raise_for_status()
            LOGGER.info("Bark 发送成功 level=%s", level)
            return True
        except Exception as exc:
            LOGGER.warning("Bark 第%s次发送失败：%s", attempt + 1, type(exc).__name__)
    return False
