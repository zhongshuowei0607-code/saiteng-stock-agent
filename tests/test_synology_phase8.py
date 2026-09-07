from pathlib import Path


def test_deployment_files_are_complete():
    env = Path(".env.example").read_text()
    for key in ("TUSHARE_TOKEN", "LLM_PROVIDER", "BARK_DEVICE_KEY", "SMTP_PASSWORD", "WEB_PORT", "API_SECRET"):
        assert key + "=" in env
    script = Path("deploy_synology.sh").read_text()
    for directory in ("data", "logs", "reports", "backup", "config"):
        assert directory in script
    assert "api/health" in script and "docker compose up -d" in script


def test_container_manager_guide_has_no_ssh_dependency():
    guide = Path("SYNOLOGY_DEPLOY.md").read_text()
    assert "完全使用 Container Manager" in guide
    assert "http://NAS_IP:18000" in guide
    assert "/volume1/docker/stock-agent/data" in guide
