from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from app.analysis.action_plan import build_action_guide
from .bark import send_bark
from .email import send_email

LOGGER = logging.getLogger("notification")
SHANGHAI = ZoneInfo("Asia/Shanghai")
_LOCKS: dict[str, Lock] = {}
_LOCKS_GUARD = Lock()


def actionable_signals(report: dict, now: datetime | None = None) -> list[dict]:
    """Use the same coordinated, data-checked actions as the dashboard."""
    return build_action_guide(report, now=now)["actions"]


class NotificationService:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_path = root / "data/notification_state.json"
        # Daily jobs and live polling may use different service instances.
        with _LOCKS_GUARD:
            self.state_lock = _LOCKS.setdefault(str(self.state_path.resolve()), Lock())

    def _state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=self.state_path.parent, delete=False, encoding="utf-8"
        ) as temporary:
            json.dump(state, temporary, ensure_ascii=False)
            name = temporary.name
        os.replace(name, self.state_path)

    def bark(self, title: str, message: str, level: str = "INFO") -> bool:
        return send_bark(title, message, level)

    def email(self, subject: str, body: str, report: Path | None = None) -> bool:
        return send_email(subject, body, report)

    def status(self) -> dict:
        """Delivery results only: no SMTP credentials, recipient or mail content."""
        with self.state_lock:
            state = self._state()
        return {
            "action": state.get("last_action_delivery"),
            "daily": state.get("last_daily_delivery"),
            "recent": state.get("delivery_history", [])[-20:][::-1],
        }

    def _email_safely(self, subject: str, body: str, page: Path) -> bool:
        try:
            return bool(self.email(subject, body, page))
        except Exception as exc:
            LOGGER.warning("邮件发送未完成：%s", type(exc).__name__)
            return False

    @staticmethod
    def _record(state: dict, item: dict, *, attempted: bool = False) -> None:
        state[f"last_{item['kind']}_delivery"] = item
        if attempted:
            history = state.setdefault("delivery_history", [])
            history.append(item)
            state["delivery_history"] = history[-100:]

    def action_alert(self, report: dict, now: datetime | None = None) -> dict:
        now = now or datetime.now(SHANGHAI)
        now = now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now.astimezone(SHANGHAI)
        # Never trust a saved decision: a quote can expire after that decision was made.
        guide = build_action_guide(report, now=now)
        signals = guide["actions"]
        market = report.get("market", {})
        market_date = market.get("date") or report.get("date")
        base = {
            "kind": "action", "checked_at": now.isoformat(),
            "market_date": market_date, "quote_time": guide.get("quote_time"),
        }
        with self.state_lock:
            state = self._state()
            if not guide.get("eligible_for_alert") or not signals:
                status = "blocked" if not guide.get("eligible_for_alert") else "no_signal"
                reason = "；".join(guide.get("blockers", [])) or guide.get("summary", "当前无行动信号")
                item = {**base, "status": status, "reason": reason}
                self._record(state, item)
                self._save_state(state)
                return {"email": status, "status": status, "reason": reason}

            sent = state.setdefault("action_alerts", {})
            output, deliveries = {}, []
            for signal in signals:
                signal_id = signal.get("signal") or signal["category"]
                if signal["category"] == "risk":
                    critical = report.get("risk_config", {}).get("critical_threshold", 85)
                    if (report.get("risk", {}).get("score") or 0) >= critical:
                        signal_id += "_CRITICAL"
                code = report.get("stock", {}).get("code", "603283.SH")
                key = "|".join(map(str, (
                    "v3", code, market_date, signal_id,
                    signal["current_shares"], signal["shares"], signal["shares_after"],
                )))
                category = signal["category"]
                item = {**base, "signal": signal_id, "category": category,
                        "direction": signal["direction"], "shares": signal["shares"],
                        "current_shares": signal["current_shares"], "key": key}
                if sent.get(key):
                    output[category] = "already_sent"
                    item.update(status="already_sent", reason="今天同一信号及仓位已通知")
                    if isinstance(sent[key], dict):
                        item["sent_at"] = sent[key].get("sent_at")
                    deliveries.append(item)
                    continue

                name = report.get("stock", {}).get("name", "赛腾股份")
                subject = f"{name} · {signal['direction']} {signal['shares']}股 · {now:%H:%M}"
                checks = signal.get("checks", [])
                check_text = "\n".join(f"{index}. {check}" for index, check in enumerate(checks, 1))
                ai = report.get("ai", {})
                ai_date = report.get("technical_as_of") or report.get("date") or "最近日报"
                body = "\n".join([
                    f"现在要做：{signal['direction']}",
                    f"处理时间：{signal.get('when', '当前交易时段内，先完成下列确认')}",
                    f"触发原因：{signal['reason']}",
                    f"行情时间：{guide.get('quote_time') or market_date}",
                    f"当前价：{market.get('close', '—')} 元",
                    f"参考价格区间：{signal['price_range']}",
                    f"参考股数：{signal['shares']} 股",
                    f"当前持仓：{signal['current_shares']} 股",
                    f"触发后参考持仓：{signal['shares_after']} 股",
                    "", "操作前逐项确认：", check_text or "核对券商实时价、可用资金与可卖数量。",
                    f"失效条件：{signal.get('invalidation', '行情过期或触发条件消失时停止采用本提示。')}",
                    "", f"风险评分：{report.get('risk', {}).get('score', '—')}",
                    f"观察状态：{report.get('watch_zone', {}).get('state') or '—'}",
                    f"最近日报 AI 摘要（{ai_date}，仅作背景参考）：{ai.get('summary') or '尚未生成'}",
                    "", "这是程序规则触发的观察提示，不执行交易，不构成投资建议。",
                ])
                page = self.root / f"reports/603283/{report.get('date')}.html"
                ok = self._email_safely(subject, body, page)
                output[category] = ok
                item.update(status="sent" if ok else "failed", sent_at=now.isoformat() if ok else None,
                            reason="已交付邮件服务器" if ok else "邮件未发送成功；下次新鲜行情轮询将重试，请检查邮件设置")
                if ok:
                    sent[key] = {"sent_at": now.isoformat(), "signal": signal_id, "market_date": market_date}
                self._record(state, item, attempted=True)
                deliveries.append(item)
                # Persist each success before attempting another signal.
                self._save_state(state)
            if deliveries:
                self._record(state, next((item for item in deliveries if item["status"] == "failed"), deliveries[-1]))
                self._save_state(state)
            return {"email": output, "status": "failed" if any(item["status"] == "failed" for item in deliveries) else "complete", "deliveries": deliveries}

    def daily(self, report: dict) -> dict:
        risk = report.get("risk", {}).get("score")
        summary = report.get("ai", {}).get("summary", "AI 未生成；请查看程序计算结果。")
        market_date = report.get("market", {}).get("date") or report["date"]
        title = f"赛腾股份日报 · {market_date} · 风险 {risk if risk is not None else '—'}"
        date = report["date"]
        guide = build_action_guide(report)
        body = "\n".join([
            f"行情日期：{market_date}；报告生成日：{date}",
            "", f"分析摘要：{summary}",
            "", f"下一步：{guide['title']}", guide["summary"],
            "", "时间安排：",
            *(f"{point['time']}：{point['task']}" for point in guide.get("schedule", [])),
            "", "重点核对：", *guide.get("checkpoints", []),
            *guide.get("blockers", []),
            "", "条件计划供人工复核；收盘日报不代表当前存在盘中交易信号。",
        ])
        html = self.root / f"reports/603283/{date}.html"
        bark = self.bark(title, summary, "WARNING" if risk and risk >= 65 else "INFO")
        with self.state_lock:
            state = self._state()
            now = datetime.now(SHANGHAI).isoformat()
            if state.get("last_daily_email_date") == market_date:
                email: bool | str = "already_sent"
            else:
                email = self._email_safely(title, body, html)
                if email:
                    state["last_daily_email_date"] = market_date
                    state["last_daily_email_sent_at"] = now
            self._record(state, {
                "kind": "daily", "checked_at": now, "report_date": date, "market_date": market_date,
                "sent_at": state.get("last_daily_email_sent_at") if email else None,
                "status": "already_sent" if email == "already_sent" else "sent" if email else "failed",
                "reason": "今天的日报已发送" if email == "already_sent" else "已交付邮件服务器" if email else "日报发送失败，下次更新可重试",
            }, attempted=email != "already_sent")
            self._save_state(state)
        return {"bark": bark, "email": email}
