import json
import os
import httpx
from .base import LLMProvider, AIReport, LLMOutputError
from .prompts import SYSTEM


class OllamaProvider(LLMProvider):
    def __init__(self, model: str, timeout: int = 60) -> None:
        self.model, self.timeout = model, timeout

    def complete(self, facts: dict) -> str:
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
                + "/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": AIReport.model_json_schema(),
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {
                            "role": "user",
                            "content": json.dumps(
                                facts, ensure_ascii=False, allow_nan=False
                            ),
                        },
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMOutputError("empty_output", "本地模型没有返回可用正文，请检查模型是否加载完成。")
            return content
