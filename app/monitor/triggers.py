from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.database.repository import Repository


def conditions(report: dict, risk_config: dict) -> dict[str, tuple[bool, str, str]]:
    state = report.get("watch_zone", {}).get("state", "")
    risk = report.get("risk", {}).get("score")
    close = report.get("market", {}).get("close")
    supports = report.get("levels", {}).get("support", [])
    resistances = report.get("levels", {}).get("resistance", [])
    return {
        "BUY_WATCH_LEVEL_1": (state == "第一加仓观察区", "WATCH", "进入第一加仓观察区"),
        "BUY_WATCH_LEVEL_2": (state == "第二加仓观察区", "WARNING", "进入第二加仓观察区"),
        "SELL_WATCH_LEVEL_1": (state == "反弹观察区", "WATCH", "进入反弹观察区"),
        "SELL_WATCH_LEVEL_2": (state == "反弹减仓观察区", "WARNING", "进入反弹减仓观察区"),
        "RISK_WARNING": (risk is not None and risk >= risk_config["warning_threshold"], "WARNING", f"风险评分达到 {risk}"),
        "CRITICAL_WARNING": (risk is not None and risk >= risk_config["critical_threshold"], "CRITICAL", f"风险评分达到 {risk}"),
        "BREAK_SUPPORT": (bool(close is not None and supports and close < supports[0]["price"]), "WARNING", "价格跌破最近支撑位"),
        "BREAK_RESISTANCE": (bool(close is not None and resistances and close > resistances[0]["price"]), "WATCH", "价格突破最近压力位"),
        "STABILIZATION_CONFIRMED": (report.get("stabilization", {}).get("level") == "HIGH", "WATCH", "企稳评分达到确认观察阈值"),
    }


class TriggerEngine:
    def __init__(self, repository: Repository, notifier, cooldown_minutes: int = 30) -> None:
        self.repository, self.notifier = repository, notifier
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def evaluate(self, report: dict, risk_config: dict, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        emitted = []
        for signal, (active, level, message) in conditions(report, risk_config).items():
            previous = self.repository.trigger_state(signal)
            old_state = previous["state"] if previous else "NOT_TRIGGERED"
            last = datetime.fromisoformat(previous["last_triggered"]) if previous and previous["last_triggered"] else None
            if not active:
                self.repository.save_trigger_state(signal, "RESET" if old_state == "TRIGGERED" else old_state, previous["last_triggered"] if previous else None, now.isoformat())
                continue
            can_emit = old_state != "TRIGGERED" and (last is None or now - last >= self.cooldown)
            triggered_at = now.isoformat() if can_emit else (previous["last_triggered"] if previous else None)
            self.repository.save_trigger_state(signal, "TRIGGERED", triggered_at, now.isoformat())
            if can_emit:
                title = f"赛腾股份 · {signal}"
                self.repository.add_trigger_event(signal, level, title, message, now.isoformat())
                self.notifier.bark(title, message, level)
                emitted.append({"signal": signal, "level": level, "message": message})
        return emitted
