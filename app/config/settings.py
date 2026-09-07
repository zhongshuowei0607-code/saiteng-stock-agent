from pathlib import Path
import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseModel):
    root: Path = ROOT
    config_dir: Path = ROOT / "config"
    config: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)

    def path(self, name: str) -> Path:
        return self.root / name


def load_settings(root: Path = ROOT) -> Settings:
    load_dotenv(root / ".env")
    config_dir = Path(os.getenv("STOCK_AGENT_CONFIG_DIR", root / "config"))
    if not (config_dir / "config.yaml").exists():
        config_dir = root / "app/config"
    config = yaml.safe_load(
        (config_dir / "config.yaml").read_text(encoding="utf-8")
    )
    for key in ("provider", "model"):
        config["llm"][key] = os.getenv("LLM_" + key.upper(), config["llm"][key])
    strategy = yaml.safe_load(
        (config_dir / "position_strategy.yaml").read_text(encoding="utf-8")
    )
    if config["llm"]["provider"] not in ("openai", "deepseek", "ollama", "disabled"):
        raise ValueError("llm.provider 必须是 openai/deepseek/ollama/disabled")
    if (
        not 0 <= config["scheduler"]["hour"] <= 23
        or not 0 <= config["scheduler"]["minute"] <= 59
    ):
        raise ValueError("定时任务小时或分钟无效")
    zones = strategy["zones"]
    if not zones or zones[0]["min"] is not None or zones[-1]["max"] is not None:
        raise ValueError("观察区间必须覆盖全部价格")
    for i, zone in enumerate(zones):
        if (
            zone["min"] is not None
            and zone["max"] is not None
            and zone["min"] >= zone["max"]
        ):
            raise ValueError("观察区间上下界错误")
        if i and zones[i - 1]["max"] != zone["min"]:
            raise ValueError("观察区间存在重叠或缺口")
    if not 0 <= strategy["confirmation_score"] <= 10:
        raise ValueError("企稳阈值必须在0到10之间")
    for folder in ("data", "reports", "logs", "backup"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return Settings(root=root, config_dir=config_dir, config=config, strategy=strategy)
