import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from .bark import send_bark
from .email import send_email


class NotificationService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_path = root / "data/notification_state.json"
        self.state_lock = Lock()

    def _state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            dir=self.state_path.parent,
            delete=False,
            encoding="utf-8",
        ) as temporary:
            json.dump(state, temporary, ensure_ascii=False)
            name = temporary.name
        os.replace(name, self.state_path)

    def bark(self, title: str, message: str, level: str = "INFO") -> bool:
        return send_bark(title, message, level)

    def email(self, subject: str, body: str, report: Path | None = None) -> bool:
        return send_email(subject, body, report)

    def daily(self, report: dict) -> dict:
        risk = report.get("risk", {}).get("score")
        summary = report.get("ai", {}).get("summary", "AI 未生成；请查看程序计算结果。")
        title = f"赛腾股份日报 · 风险 {risk if risk is not None else '—'}"
        date = report["date"]
        html = self.root / f"reports/603283/{date}.html"
        bark = self.bark(
            title, summary, "WARNING" if risk and risk >= 65 else "INFO"
        )
        with self.state_lock:
            state = self._state()
            if state.get("last_daily_email_date") == date:
                email: bool | str = "already_sent"
            else:
                email = self.email(title, summary, html)
                if email:
                    state["last_daily_email_date"] = date
                    self._save_state(state)
        return {"bark": bark, "email": email}
