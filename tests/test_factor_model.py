from app.analysis.factor_model import build_factor_snapshot
from app.indicators.technical import calculate
from test_phase2 import sample


def technical():
    return calculate(sample(300))


def report():
    return {
        "technical": {"date": "2026-11-04"},
        "stock": {"code": "603283.SH"},
        "market": {"pe": 20, "pb": 3},
        "trend": {"medium": {"state": "BULL"}},
        "industry": {
            "rows": [
                {"code": "603283.SH", "return20": 5, "pe": 20},
                {"code": "688097.SH", "return20": 8, "pe": 30},
                {"code": "002475.SZ", "return20": 3, "pe": 25},
                {"code": "601138.SH", "return20": -2, "pe": 35},
            ]
        },
        "fundamental": {
            "rows": [{"profit_yoy": 20, "revenue_yoy": 10}],
            "warnings": [],
            "yoy_changes": {"operating_cashflow": 5},
        },
        "announcements": [],
        "news": [],
    }


def test_factor_snapshot_has_transparent_factors():
    result = build_factor_snapshot(technical(), report())
    assert result["version"] == "factor-v1"
    assert len(result["factors"]) == 9
    assert result["composite"] is not None
    assert 0 <= result["composite"] <= 100
    assert result["coverage"] > 0
    assert result["event_veto"] is False
    assert {"reversal", "momentum", "quality", "growth", "event"} <= {
        item["name"] for item in result["factors"]
    }


def test_control_change_event_vetoes_composite():
    facts = report()
    facts["announcements"] = [
        {"categories": ["股权质押", "控制权变更"], "risk_flag": True}
    ]
    result = build_factor_snapshot(technical(), facts)
    assert result["event_veto"] is True
    assert result["status"] == "event_veto"
    assert result["composite"] <= 35


def test_factor_snapshot_handles_missing_data():
    result = build_factor_snapshot(None, {})
    assert result["composite"] is None
    assert result["status"] in ("unavailable", "low_confidence")
    assert result["missing"]
