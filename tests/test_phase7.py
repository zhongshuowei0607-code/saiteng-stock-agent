import json
import subprocess
from pathlib import Path
import pytest
from app.analysis.locking import analysis_lock
from app.analysis.risk_analyzer import risk_score
from app.analysis.comparison import compare
from app.data.bounded import fetch
from app.data.market_provider import validate
from app.llm.base import explain
from app.llm.openai_provider import OpenAIProvider
from app.llm.deepseek_provider import DeepSeekProvider
from app.llm.ollama_provider import OllamaProvider
from app.config.settings import load_settings
from app.portfolio.portfolio_service import watch_state
from test_phase1 import bars
from test_phase3 import valid_ai


def test_negative_volume():
    frame = bars()
    frame.loc[0, "volume"] = -1
    with pytest.raises(ValueError):
        validate(frame)


def test_process_lock(tmp_path):
    with analysis_lock(tmp_path / "lock"):
        with pytest.raises(RuntimeError):
            with analysis_lock(tmp_path / "lock"):
                pass
    with analysis_lock(tmp_path / "lock"):
        pass


def test_timeout(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired("worker", 1)

    monkeypatch.setattr("app.data.bounded.subprocess.run", fail)
    with pytest.raises(subprocess.TimeoutExpired):
        fetch("stock_news_em", {}, timeout=1)


def test_numeric_hallucination():
    data = valid_ai()
    data["summary"] = "股价12345.67元"

    class Mock:
        def complete(self, facts):
            return json.dumps(data)

    assert explain(Mock(), {"market": {"close": 43.7}})["status"] == "unavailable"


@pytest.mark.parametrize(
    "provider,envkey,endpoint",
    [
        (OpenAIProvider, "OPENAI_API_KEY", "/chat/completions"),
        (DeepSeekProvider, "DEEPSEEK_API_KEY", "/chat/completions"),
        (OllamaProvider, None, "/api/chat"),
    ],
)
def test_llm_wire_contract(monkeypatch, provider, envkey, endpoint):
    seen = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "{}"}}],
                "message": {"content": "{}"},
            }

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            seen.append((url, kwargs))
            return Response()

    monkeypatch.setattr("httpx.Client", Client)
    if envkey:
        monkeypatch.setenv(envkey, "test-only-key")
    assert provider("test-model").complete({"market": {"close": 43.7}}) == "{}"
    assert seen[0][0].endswith(endpoint)
    assert seen[0][1]["json"]["messages"][1]["content"] == json.dumps(
        {"market": {"close": 43.7}}, ensure_ascii=False
    )
    if envkey:
        assert seen[0][1]["json"]["max_tokens"] == 1600
    assert "工具" in seen[0][1]["json"]["messages"][0]["content"]


def risk_facts():
    return dict(
        market={"close": 40, "pct_change": -8, "pe": None},
        technical={"ATR": 3, "volume_signal": "放量下跌"},
        portfolio={"pnl_pct": -20},
        trend={"medium": {"state": "STRONG_BEAR"}},
        industry={},
        fundamental={},
        news=[],
        announcements=[],
    )


def test_risk_direction_and_missing():
    facts = risk_facts()
    high = risk_score(facts)
    assert high["score"] >= 65 and "估值" in high["missing"]
    facts["market"]["pct_change"] = 3
    facts["technical"] = {"ATR": 0.2, "volume_signal": "放量上涨"}
    facts["portfolio"]["pnl_pct"] = 20
    facts["trend"]["medium"]["state"] = "STRONG_BULL"
    low = risk_score(facts)
    assert low["score"] < high["score"] and low["score"] < 35
    facts["industry"] = {
        "rows": [{"code": "603283.SH"}],
        "relative": "数据不足，无法判断。",
    }
    assert "行业" in risk_score(facts)["missing"]


def test_breakout_and_event_override():
    strategy = load_settings().strategy
    assert (
        watch_state(49, {"score": 8}, strategy, {"breakout_confirmed": True})["state"]
        == "突破确认区"
    )
    result = watch_state(42.5, {"score": 10}, strategy, event_stop=True)
    assert result["state"] == "高风险区" and not result["confirmed"]


def test_config_gap(tmp_path):
    import shutil, yaml

    settings = load_settings()
    shutil.copytree(settings.path("app/config"), tmp_path / "app/config")
    path = tmp_path / "app/config/position_strategy.yaml"
    data = yaml.safe_load(path.read_text())
    data["zones"][1]["min"] = 40.6
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="重叠或缺口"):
        load_settings(tmp_path)


def test_comparison_actual_cross():
    import copy

    old = {
        "date": "2026-09-03",
        "market": {"date": "2026-09-03"},
        "stock": {"code": "603283.SH"},
        "technical": {"close": 50, "MA20": 49, "volume_signal": "缩量上涨"},
        "risk": {"score": 55, "coverage": 0.8},
        "trend": {},
        "watch_zone": {"state": "持仓观察"},
    }
    new = copy.deepcopy(old)
    new["technical"] = {"close": 48, "MA20": 49, "volume_signal": "放量下跌"}
    new["risk"]["score"] = 70
    result = compare(old, new)
    assert "跌破 MA20" in result["changes"]
    assert result["risk"] == {"from": 55, "to": 70}


def test_flat_volume_is_not_decline():
    from test_phase2 import sample
    from app.indicators.technical import calculate

    frame = sample()
    frame.loc[frame.index[-1], "pre_close"] = frame.iloc[-1].close
    frame.loc[frame.index[-1], "volume"] = 1000
    assert calculate(frame).iloc[-1].volume_signal == "量价变化不显著"


def test_report_active_content_removed():
    from app.analysis.sanitize import sanitize
    import markdown

    result = sanitize(
        markdown.markdown(
            "[恶意链接](javascript:alert(1)) <img src=x onerror=alert(1)>"
        )
    )
    assert (
        "javascript:" not in result and "onerror" not in result and "<img" not in result
    )


def test_bounded_retry(monkeypatch):
    calls = []

    def fake(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.CalledProcessError(1, "worker")
        return subprocess.CompletedProcess("worker", 0, stdout='RESULT_JSON:[{"x":1}]')

    monkeypatch.setattr("app.data.bounded.subprocess.run", fake)
    assert fetch("stock_news_em", {}).iloc[0]["x"] == 1 and len(calls) == 2


def test_moneyflow_units(monkeypatch):
    import pandas as pd
    from app.data.moneyflow_provider import moneyflow

    monkeypatch.setattr(
        "app.data.moneyflow_provider.fetch",
        lambda *args: pd.DataFrame([{"trade_date": "20260904", "net_mf_amount": -50}]),
    )
    assert moneyflow("603283.SH", "2026-09-04")["net_amount"] == -500000
