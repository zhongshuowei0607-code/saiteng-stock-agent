from __future__ import annotations

import json
import os
from pathlib import Path
import bcrypt
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from sqlalchemy import Engine, text, create_engine

SECRET_KEYS = {"TUSHARE_TOKEN", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "BARK_DEVICE_KEY", "SMTP_PASSWORD", "API_SECRET", "WEB_PASSWORD_HASH"}
DATABASE_ENV_VALUES: dict[str, str] = {}


class SecureSettings:
    def __init__(self, engine: Engine, root: Path) -> None:
        self.engine = engine
        file_values = dotenv_values(root / ".env")
        self.external_keys = {
            key for key, value in file_values.items() if value
        } | {
            key
            for key, value in os.environ.items()
            if value and DATABASE_ENV_VALUES.get(key) != value
        }
        self.key_file = root / "data/.settings.key"
        if not self.key_file.exists():
            self.key_file.write_bytes(Fernet.generate_key())
            try:
                self.key_file.chmod(0o600)
            except OSError:
                pass
        self.cipher = Fernet(self.key_file.read_bytes())
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, secret INTEGER NOT NULL DEFAULT 0)"))

    def set(self, key: str, value: object, secret: bool | None = None) -> None:
        secret = key in SECRET_KEYS if secret is None else secret
        raw = json.dumps(value, ensure_ascii=False)
        stored = self.cipher.encrypt(raw.encode()).decode() if secret else raw
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO app_settings(key,value,secret) VALUES(:k,:v,:s) ON CONFLICT(key) DO UPDATE SET value=:v,secret=:s"), {"k": key, "v": stored, "s": int(secret)})

    def get(self, key: str, default: object = None) -> object:
        if key in self.external_keys and os.getenv(key):
            return os.environ[key]
        with self.engine.connect() as connection:
            row = connection.execute(text("SELECT value,secret FROM app_settings WHERE key=:k"), {"k": key}).first()
        if not row:
            return default
        raw = self.cipher.decrypt(row.value.encode()).decode() if row.secret else row.value
        return json.loads(raw)

    def is_complete(self) -> bool:
        return str(self.get("SETUP_COMPLETE", "false")).lower() == "true"

    def apply_environment(self) -> None:
        names = SECRET_KEYS | {"LLM_PROVIDER", "LLM_MODEL", "BARK_ENABLED", "EMAIL_ENABLED", "SMTP_HOST", "SMTP_PORT", "SMTP_USE_SSL", "SMTP_USER", "SMTP_FROM", "SMTP_TO", "OLLAMA_URL", "DASHBOARD_PUBLIC_URL"}
        for key in names:
            if key not in self.external_keys:
                value = self.get(key)
                if value not in (None, ""):
                    os.environ[key] = str(value)
                    DATABASE_ENV_VALUES[key] = str(value)

    def apply_llm_config(self, config: dict) -> None:
        self.apply_environment()
        for field in ("provider", "model"):
            key = "LLM_" + field.upper()
            value = self.get(key, config["llm"][field])
            if value:
                config["llm"][field] = str(value)

    def set_password(self, password: str) -> None:
        if len(password) < 10:
            raise ValueError("Dashboard 密码至少 10 位")
        self.set("WEB_PASSWORD_HASH", bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(), True)

    def verify_password(self, password: str) -> bool:
        hashed = self.get("WEB_PASSWORD_HASH")
        return bool(hashed) and bcrypt.checkpw(password.encode(), str(hashed).encode())

    def masked(self, key: str) -> str:
        return "••••••••" if self.get(key) else ""


def create_secure_settings(root: Path) -> SecureSettings:
    engine = create_engine("sqlite:///" + str(root / "data/settings.db"), connect_args={"check_same_thread": False, "timeout": 30})
    return SecureSettings(engine, root)
