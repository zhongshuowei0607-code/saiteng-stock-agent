import json
import os
import httpx
from .base import LLMProvider
from .prompts import SYSTEM


class OpenAIProvider(LLMProvider):
    key_name = "OPENAI_API_KEY"
    default_url = "https://api.openai.com/v1"

    def __init__(
        self, model: str, timeout: int = 60, base_url: str | None = None
    ) -> None:
        self.model, self.timeout, self.base_url = (
            model,
            timeout,
            base_url or self.default_url,
        )

    def complete(self, facts: dict) -> str:
        key = os.getenv(self.key_name)
        if not key:
            raise ValueError("缺少模型 API Key")
        timeout = httpx.Timeout(
            self.timeout,
            connect=min(self.timeout, 10),
            read=min(self.timeout, 30),
            write=min(self.timeout, 10),
            pool=min(self.timeout, 5),
        )
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM},
                        {
                            "role": "user",
                            "content": json.dumps(
                                facts, ensure_ascii=False, allow_nan=False
                            ),
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": 2400,
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
