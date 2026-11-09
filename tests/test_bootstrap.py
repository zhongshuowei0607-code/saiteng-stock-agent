import json
import shutil

from app.bootstrap import bootstrap
from sqlalchemy import text


def test_fresh_bootstrap_and_upgrade(tmp_path):
    shutil.copytree("app/config", tmp_path / "app/config")
    shutil.copy("VERSION", tmp_path / "VERSION")
    settings, repository = bootstrap(tmp_path)
    assert settings.path("data/portfolio.json").exists()
    assert settings.path("backup").is_dir()
    position = json.loads(settings.path("data/portfolio.json").read_text())
    assert position["max_shares"] == 1100
    with repository.engine.connect() as connection:
        assert connection.execute(text("SELECT value FROM system_meta WHERE key='schema_version'" )).scalar_one() == "2"
    # 重复启动即模拟升级，不覆盖用户持仓。
    position["max_shares"] = 1200
    settings.path("data/portfolio.json").write_text(json.dumps(position))
    _, second = bootstrap(tmp_path)
    assert json.loads(settings.path("data/portfolio.json").read_text())["max_shares"] == 1200
    assert second.engine is not None

