from abc import ABC, abstractmethod
import json
import logging
import re
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class EventInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    category: str
    importance: int = Field(ge=0, le=100)
    sentiment: Literal["positive", "neutral", "negative", "unknown"]
    summary: str
    impact: str
    horizon: str
    affects_thesis: bool | None
    stop_adding_observation: bool | None


class AIReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    trend: str
    risk: str
    portfolio_analysis: str
    watch_zone: str
    stabilization: str
    bullish_factors: list[str]
    bearish_factors: list[str]
    next_day_focus: list[str]
    conclusion: str
    events: list[EventInterpretation] = Field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, facts: dict) -> str: ...


def explain(provider: LLMProvider | None, facts: dict) -> dict:
    if provider is None or not facts.get("market"):
        return {
            "status": "unavailable",
            "summary": "数据不足，无法判断。AI 未生成，以下为程序计算结果。",
            "events": [],
        }
    try:
        logging.info("LLM 调用开始 provider=%s", type(provider).__name__)
        result = AIReport.model_validate_json(provider.complete(facts)).model_dump()
        text = json.dumps(result, ensure_ascii=False)
        if any(
            word in text
            for word in ("立即买入", "立即卖出", "立刻买入", "立刻卖出", "保证盈利")
        ):
            raise ValueError("模型输出越过观察边界")
        ids = {x["id"] for x in facts.get("news", []) + facts.get("announcements", [])}
        if any(event["id"] not in ids for event in result["events"]):
            raise ValueError("模型引用不存在的事件")
        # 允许对已有事实做轻微四舍五入，也允许普通序号；明显新增的
        # 小数或大额数字仍拒绝，避免模型改写价格、比例和金额。
        number_pattern = r"(?<![a-zA-Z])[-+]?\d+(?:\.\d+)?"
        known = [
            Decimal(number)
            for number in re.findall(
                number_pattern, json.dumps(facts, ensure_ascii=False)
            )
        ]
        def sanitize_numbers(value, key: str | None = None):
            if isinstance(value, dict):
                return {
                    child_key: sanitize_numbers(child_value, child_key)
                    for child_key, child_value in value.items()
                }
            if isinstance(value, list):
                return [sanitize_numbers(item, key) for item in value]
            if not isinstance(value, str) or key == "id":
                return value

            def replace(match: re.Match) -> str:
                token = match.group(0)
                number = Decimal(token)
                if "." not in token and abs(number) <= 100:
                    return token
                if any(
                    abs(number - fact)
                    <= max(Decimal("0.05"), abs(fact) / 1000)
                    for fact in known
                ):
                    return token
                logging.warning("已移除模型输出中的未提供数值：%s", token)
                return "相关数值"

            return re.sub(number_pattern, replace, value)

        result = sanitize_numbers(result)
        for event in result["events"]:
            source = next(
                x
                for x in facts.get("news", []) + facts.get("announcements", [])
                if x["id"] == event["id"]
            )
            if not source.get("raw_text"):
                event["affects_thesis"] = None
                event["stop_adding_observation"] = None
                event["impact"] = "数据不足，无法判断。仅获取标题。"
        result["status"] = "generated"
        return result
    except Exception as exc:
        reason = str(exc).splitlines()[0][:160]
        logging.warning(
            "LLM 不可用或输出校验失败：%s reason=%s",
            type(exc).__name__,
            reason,
        )
        return {
            "status": "unavailable",
            "summary": "数据不足，无法判断。AI 未生成或输出未通过校验；请查看程序计算事实。",
            "reason": type(exc).__name__,
            "events": [],
        }
