from pathlib import Path
import os
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field
ROOT = Path(__file__).resolve().parents[2]
class Settings(BaseModel):
    root: Path = ROOT
    config: dict = Field(default_factory=dict)
    strategy: dict = Field(default_factory=dict)
    def path(self, name: str) -> Path:
        return self.root / name

def load_settings(root: Path = ROOT) -> Settings:
    load_dotenv(root / ".env")
    config = yaml.safe_load((root / "app/config/config.yaml").read_text(encoding="utf-8"))
    for key in ("provider", "model"):
        config["llm"][key] = os.getenv("LLM_" + key.upper(), config["llm"][key])
    strategy = yaml.safe_load((root / "app/config/position_strategy.yaml").read_text(encoding="utf-8"))
    for folder in ("data", "reports", "logs"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    return Settings(root=root, config=config, strategy=strategy)
