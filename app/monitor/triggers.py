from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from app.analysis.action_plan import build_action_guide
from app.database.repository import Repository


TRIGGER_SIGNALS = (
    "BUY_WATCH_LEVEL_1", "BUY_WATCH_LEVEL_2", "SELL_WATCH_LEVEL_1",
    "SELL_WATCH_LEVEL_2", "RISK_WARNING", "CRITICAL_WARNING",
    "BREAK_SUPPORT", "BREAK_RESISTANCE", "STABILIZATION_CONFIRMED",
)


class TriggerEngine:
    def __init__(self, repository: Repository, notifier, cooldown_minutes: int = 30) -> None:
        self.repository, self.notifier = repository, notifier
        self.cooldown = timedelta(minutes=cooldown_minutes)

    def evaluate(self, report: dict, risk_config: dict, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        now = now.replace(tzinfo=ZoneInfo("Asia/Shanghai")) if now.tzinfo is None else now.astimezone(ZoneInfo("Asia/Shanghai"))
        report = {**report, "risk_config": risk_config}
        guide = build_action_guide(report, now=now)
        # Email delivery has its own persistent retry/deduplication state. A Bark
        # event marked TRIGGERED must never consume a failed email attempt.
        if hasattr(self.notifier, "action_alert"):
            self.notifier.action_alert(report, now=now)
        if not guide.get("eligible_for_alert"):
            return []
        actions = {action["signal"]: action for action in guide["actions"]}
        risk_action = actions.pop("RISK_REVIEW", None)
        if risk_action:
            critical = (report.get("risk", {}).get("score") or 0) >= risk_config.get("critical_threshold", 85)
            actions["CRITICAL_WARNING" if critical else "RISK_WARNING"] = risk_action
        if "BREAKOUT_CONFIRMED" in actions:
            actions["BREAK_RESISTANCE"] = actions.pop("BREAKOUT_CONFIRMED")
        emitted = []
        for signal in TRIGGER_SIGNALS:
            action = actions.get(signal)
            active = action is not None
            level = "CRITICAL" if signal == "CRITICAL_WARNING" else "WARNING" if action and action["category"] != "buy" else "WATCH"
            message = "" if action is None else f"{action['reason']}；参考 {action['shares']} 股。{action['when']}；请先核对实时价格与可用仓位。"
            previous = self.repository.trigger_state(signal)
            old_state = previous["state"] if previous else "NOT_TRIGGERED"
            last = datetime.fromisoformat(previous["last_triggered"]) if previous and previous["last_triggered"] else None
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            if not active:
                self.repository.save_trigger_state(signal, "RESET" if old_state in ("TRIGGERED", "PENDING") else old_state, previous["last_triggered"] if previous else None, now.isoformat())
                continue
            new_day = last is not None and last.astimezone(ZoneInfo("Asia/Shanghai")).date() != now.date()
            can_emit = (old_state != "TRIGGERED" or new_day) and (last is None or now - last >= self.cooldown)
            triggered_at = now.isoformat() if can_emit else (previous["last_triggered"] if previous else None)
            # A signal restored during cooldown remains pending until it can be
            # emitted, instead of being marked consumed before any delivery.
            state = "TRIGGERED" if can_emit or (old_state == "TRIGGERED" and not new_day) else "PENDING"
            self.repository.save_trigger_state(signal, state, triggered_at, now.isoformat())
            if can_emit:
                title = f"赛腾股份 · {signal}"
                self.repository.add_trigger_event(signal, level, title, message, now.isoformat())
                self.notifier.bark(title, message, level)
                emitted.append({"signal": signal, "level": level, "message": message})
        return emitted
