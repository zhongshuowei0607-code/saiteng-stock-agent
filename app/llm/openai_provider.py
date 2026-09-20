import json
import os
import httpx
from .base import LLMProvider, LLMOutputError
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
            read=min(self.timeout, 90),
            write=min(self.timeout, 10),
            pool=min(self.timeout, 5),
        )
        payload = {
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
            "max_tokens": 4000 if facts.get("_generation_retry") else 2600,
        }
        if self.key_name == "DEEPSEEK_API_KEY":
            payload["thinking"] = {"type": "disabled"}
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                self.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": "Bearer " + key},
                json=payload,
            )
            response.raise_for_status()
            choice = response.json()["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMOutputError("truncated_output", "模型输出达到长度上限，未形成完整分析。")
            content = choice["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise LLMOutputError("empty_output", "模型没有返回可用正文，请检查模型配置后重试。")
            return content
