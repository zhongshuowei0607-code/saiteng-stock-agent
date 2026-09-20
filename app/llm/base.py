from abc import ABC, abstractmethod
import json
import logging
import re
import time
from decimal import Decimal
from typing import Literal
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .fallback import data_coverage, rules_explanation


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


class LLMOutputError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _failure(exc: Exception) -> tuple[str, str, bool]:
    """Return actionable public errors without exposing keys, URLs or response bodies."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        messages = {
            400: "模型服务拒绝了请求格式，请核对模型名称与服务兼容性。",
            401: "模型 API Key 无效或已过期，请在设置中更新。",
            403: "模型账户无访问权限，请核对账户和模型权限。",
            404: "模型或服务地址不存在，请核对设置中的模型名称与地址。",
            429: "模型服务限流或额度不足，请稍后重试并核对账户额度。",
        }
        return f"http_{code}", messages.get(code, f"模型服务请求失败（HTTP {code}），请稍后重试。"), code in (408, 429) or code >= 500
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "模型响应超时；可稍后重试，或检查网络与模型超时设置。", True
    if isinstance(exc, httpx.RequestError):
        return "network_error", "无法连接模型服务，请检查网络或本地模型是否启动。", True
    if isinstance(exc, LLMOutputError):
        return exc.code, str(exc), True
    if isinstance(exc, (ValidationError, json.JSONDecodeError)):
        return "invalid_output", "模型输出未通过结构校验，已保留程序事实解读。", True
    if isinstance(exc, ValueError) and str(exc) == "缺少模型 API Key":
        return "missing_api_key", "尚未配置模型 API Key，请在设置中补全。", False
    return "invalid_output", "模型返回内容未通过校验，已保留程序事实解读。", True


def _parse_json_object(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return value


def explain(provider: LLMProvider | None, facts: dict, *, unavailable_reason: str | None = None) -> dict:
    coverage = data_coverage(facts)
    if not coverage["has_core_facts"]:
        return rules_explanation(facts, "没有可供解释的核心事实，请先更新行情或持仓。", "no_core_data")
    if provider is None:
        return rules_explanation(facts, unavailable_reason or "AI 未启用；可在设置中启用并配置模型。", "configuration_error" if unavailable_reason else "disabled")
    number_pattern = r"(?<![a-zA-Z0-9.])[-+]?\d+(?:\.\d+)?"
    known = [
        Decimal(number)
        for number in re.findall(
            number_pattern, json.dumps(facts, ensure_ascii=False)
        )
    ]

    removed_numbers = []

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
            if number in known:
                return token
            removed_numbers.append(token)
            logging.warning("已移除模型输出中的未提供数值")
            return "相关数值"

        return re.sub(number_pattern, replace, value)

    last_error: Exception | None = None
    retry_code = ""
    for attempt in range(2):
        try:
            logging.info(
                "LLM 调用开始 provider=%s attempt=%s",
                type(provider).__name__,
                attempt + 1,
            )
            request_facts = facts if attempt == 0 else {
                **facts,
                "_generation_retry": {
                    "reason": retry_code,
                    "instruction": "重新生成完整且精简的 JSON，严格遵守 schema。基于可用核心事实解释，仅在缺失资料对应字段标明限制，不要拒绝整份分析。",
                },
            }
            result = AIReport.model_validate(
                _parse_json_object(provider.complete(request_facts))
            ).model_dump()
            if not result["summary"].strip() or result["summary"].strip().startswith(("数据不足，无法", "数据不足,无法", "无法分析")):
                raise LLMOutputError("unsupported_refusal", "模型未解释已有核心事实，已改用程序规则解读。")
            text = json.dumps(result, ensure_ascii=False)
            if any(
                word in text
                for word in ("立即买入", "立即卖出", "立刻买入", "立刻卖出", "保证盈利")
            ):
                raise LLMOutputError("unsafe_output", "模型输出包含未经确认的交易指令，已拦截并保留程序规则解读。")
            ids = {
                item["id"]
                for item in facts.get("news", []) + facts.get("announcements", [])
            }
            if any(event["id"] not in ids for event in result["events"]):
                raise LLMOutputError("unknown_event", "模型引用了未提供的事件，已拦截并保留程序规则解读。")
            result = sanitize_numbers(result)
            for event in result["events"]:
                source = next(
                    item
                    for item in facts.get("news", []) + facts.get("announcements", [])
                    if item["id"] == event["id"]
                )
                if not source.get("raw_text"):
                    event["affects_thesis"] = None
                    event["stop_adding_observation"] = None
                    impact = str(event.get("impact", "")).strip()
                    if not impact or "无法判断" in impact:
                        event["impact"] = "仅据标题，无法确认具体影响。"
                    elif not impact.startswith("仅据标题"):
                        event["impact"] = "仅据标题：" + impact
            result["status"] = "generated"
            result["mode"] = "llm"
            result["label"] = "AI 事实解读"
            result["attempts"] = attempt + 1
            result["data_coverage"] = coverage
            if removed_numbers:
                result["validation_warnings"] = ["模型文字中的未提供数值已移除，请以程序事实为准。"]
            return result
        except Exception as exc:
            last_error = exc
            retry_code, reason, retryable = _failure(exc)
            if attempt == 0:
                logging.warning(
                    "LLM 调用失败：%s code=%s retry=%s",
                    type(exc).__name__,
                    retry_code,
                    retryable,
                )
            if not retryable:
                break
            if attempt == 0 and isinstance(exc, (httpx.RequestError, httpx.HTTPStatusError)):
                # Brief backoff avoids immediately repeating a transient failure.
                time.sleep(1)

    exc = last_error or RuntimeError("LLM 未返回结果")
    code, reason, retryable = _failure(exc)
    logging.warning(
        "LLM 不可用或输出校验失败：%s code=%s",
        type(exc).__name__,
        code,
    )
    return rules_explanation(facts, reason, code, attempts=attempt + 1, retryable=retryable)
