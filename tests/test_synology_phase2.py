from app.config.logging_config import configure_logging
from app.system.resources import resource_snapshot


def test_rotating_logs_and_resources(tmp_path):
    for name in ("data", "logs", "reports"):
        (tmp_path / name).mkdir()
    (tmp_path / "data/stock_agent.db").write_bytes(b"db")
    configure_logging(tmp_path)
    for name in ("app.log", "error.log", "market.log", "monitor.log", "notification.log"):
        assert (tmp_path / "logs" / name).exists()
    snapshot = resource_snapshot(tmp_path)
    assert snapshot["process_memory_mb"] > 0
    assert snapshot["database_size_bytes"] == 2
