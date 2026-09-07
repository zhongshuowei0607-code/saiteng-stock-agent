from pathlib import Path
from .bark import send_bark
from .email import send_email


class NotificationService:
    def __init__(self, root: Path) -> None:
        self.root = root

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
        return {"bark": self.bark(title, summary, "WARNING" if risk and risk >= 65 else "INFO"), "email": self.email(title, summary, html)}
