from pathlib import Path
from .position import Position


def load_position(path: Path) -> Position:
    return Position.model_validate_json(path.read_text(encoding="utf-8"))


def watch_state(
    price: float | None,
    stabilization: dict,
    strategy: dict,
    resistance: dict | None = None,
    event_stop: bool = False,
) -> dict:
    if price is None:
        return {"state": None, "message": "数据不足，无法判断。", "confirmed": False, "event_stop": bool(event_stop)}
    state = next(
        (
            zone["label"]
            for zone in strategy["zones"]
            if (zone["min"] is None or price >= zone["min"])
            and (zone["max"] is None or price < zone["max"])
        ),
        "未配置观察区",
    )
    score = stabilization.get("score")
    confirmed = score is not None and score >= strategy["confirmation_score"]
    if event_stop:
        return {
            "state": "事件风险",
            "message": "重大事件风险触发，暂停补仓观察，核对公告原文。",
            "confirmed": False,
            "event_stop": True,
        }
    if resistance and resistance.get("breakout_confirmed"):
        state = "突破确认区"
    message = f"当前处于{state}。"
    if "加仓" in state:
        message += (
            "企稳信号达到观察阈值，仍需核对事件与风险。"
            if confirmed
            else "企稳信号不足，继续观察。"
        )
    return {"state": state, "message": message, "confirmed": confirmed, "event_stop": False}
