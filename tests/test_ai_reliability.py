import copy
import json

import httpx
import pytest

from app.llm.base import LLMOutputError, explain
from app.llm.deepseek_provider import DeepSeekProvider
from test_phase3 import valid_ai


class Provider:
    def __init__(self, *results):
        self.results = results
        self.calls = []

    def complete(self, facts):
        self.calls.append(copy.deepcopy(facts))
        result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return json.dumps(result, ensure_ascii=False)


def test_optional_sources_do_not_prevent_ai_analysis():
    provider = Provider(valid_ai())
    result = explain(provider, {"market": {"close": 43.7}, "fundamental": {}, "news": [], "announcements": []})
    assert result["status"] == "generated"
    assert result["mode"] == "llm"
    assert result["data_coverage"]["available"] == ["行情"]
    assert "财务" in result["data_coverage"]["missing"]


def test_technical_facts_are_enough_without_market():
    provider = Provider(valid_ai())
    assert explain(provider, {"technical": {"MA20": 43.7}})["status"] == "generated"
    assert len(provider.calls) == 1


def test_metadata_alone_is_not_core_data():
    provider = Provider(valid_ai())
    result = explain(provider, {"market": {"date": "2026-09-18"}, "technical": {"MA20": None}})
    assert result["mode"] == "unavailable"
    assert result["reason_code"] == "no_core_data"
    assert not provider.calls


def test_disabled_model_has_labelled_rules_and_exact_facts():
    facts = {
        "market": {"date": "2026-09-18", "close": 43.7},
        "trend": {"short": {"state": "BEAR"}},
        "risk": {"score": 62, "missing": ["资金流"]},
        "levels": {"support": [{"price": 42.1}]},
    }
    result = explain(None, facts)
    assert result["status"] == "unavailable"
    assert result["mode"] == "rules"
    assert result["reason_code"] == "disabled"
    assert "43.7" in result["summary"] and "2026-09-18" in result["summary"]
    assert "短期趋势规则判定为偏弱" in result["trend"]
    assert "62" in result["risk"] and "资金流" in result["risk"]
    assert "42.1" in result["next_day_focus"][1]
    assert "AI 解读暂不可用" in result["conclusion"]


def test_invalid_schema_gets_one_feedback_retry_without_mutating_facts():
    facts = {"market": {"close": 43.7}}
    provider = Provider({"summary": "Incomplete"}, valid_ai())
    result = explain(provider, facts)
    assert result["status"] == "generated" and result["attempts"] == 2
    assert provider.calls[1]["_generation_retry"]["reason"] == "invalid_output"
    assert "_generation_retry" not in facts


def test_blanket_refusal_with_valid_facts_falls_back_to_rules():
    refusal = {**valid_ai(), "summary": "数据不足，无法判断。"}
    result = explain(Provider(refusal), {"market": {"close": 43.7}})
    assert result["status"] == "unavailable" and result["mode"] == "rules"
    assert result["reason_code"] == "unsupported_refusal"
    assert "43.7" in result["summary"]


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (404, 1), (429, 2), (503, 2)])
def test_http_errors_are_actionable_and_do_not_leak_secrets(status, attempts):
    request = httpx.Request("POST", "https://example.invalid/private-api-key")
    error = httpx.HTTPStatusError("private-token: sensitive request", request=request, response=httpx.Response(status, request=request))
    provider = Provider(error)
    result = explain(provider, {"market": {"close": 43.7}})
    assert result["reason_code"] == f"http_{status}"
    assert result["attempts"] == attempts and len(provider.calls) == attempts
    assert "private" not in json.dumps(result)
    assert result["mode"] == "rules"


def test_missing_key_is_not_retried():
    provider = Provider(ValueError("缺少模型 API Key"))
    result = explain(provider, {"market": {"close": 43.7}})
    assert result["reason_code"] == "missing_api_key"
    assert len(provider.calls) == 1


def test_timeout_recovers_without_reporting_data_insufficient():
    provider = Provider(httpx.ReadTimeout("private request"), valid_ai())
    result = explain(provider, {"market": {"close": 43.7}})
    assert result["status"] == "generated" and result["attempts"] == 2


def test_long_fact_decimals_are_rounded_for_readability():
    report = {**valid_ai(), "summary": "浮亏-15.6716778653%，MA20为40.9615"}
    result = explain(
        Provider(report),
        {"market": {"close": 34.89}, "portfolio": {"pnl_pct": -15.6716778653}, "technical": {"MA20": 40.9615}},
    )
    assert "-15.67%" in result["summary"]
    assert "40.9615" in result["summary"]


def test_small_hallucinated_financial_number_is_removed():
    report = {**valid_ai(), "summary": "预计到达99元"}
    result = explain(Provider(report), {"market": {"close": 43.7}})
    assert "99" not in result["summary"]
    assert result["validation_warnings"]


def test_unknown_event_still_rejected_after_retries():
    report = valid_ai()
    report["events"] = [{"id": "fake", "category": "公告", "importance": 40, "sentiment": "neutral", "summary": "未提供事件", "impact": "未知", "horizon": "短期", "affects_thesis": None, "stop_adding_observation": None}]
    result = explain(Provider(report), {"market": {"close": 43.7}})
    assert result["reason_code"] == "unknown_event"
    assert result["events"] == [] and result["mode"] == "rules"


def test_length_limit_is_detected_even_with_nonempty_body(monkeypatch):
    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"summary": "partial'}}]}, request=httpx.Request("POST", url))

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr("httpx.Client", Client)
    with pytest.raises(LLMOutputError) as error:
        DeepSeekProvider("test").complete({"market": {"close": 43.7}})
    assert error.value.code == "truncated_output"
