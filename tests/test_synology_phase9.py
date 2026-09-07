from pathlib import Path


def test_upgrade_preserves_persistent_directories():
    script = Path("upgrade_synology.sh").read_text()
    assert "run.py backup" in script
    assert "run.py migrate" in script
    assert "api/health" in script
    for destructive in ("rm -rf data", "rm -rf logs", "rm -rf reports", "docker compose down -v"):
        assert destructive not in script
    assert Path("VERSION").read_text().strip() == "1.0.0"
