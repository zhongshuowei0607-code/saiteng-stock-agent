from .base import LLMProvider
from .openai_provider import OpenAIProvider
from .deepseek_provider import DeepSeekProvider
from .ollama_provider import OllamaProvider


def make_provider(config: dict) -> LLMProvider | None:
    classes = {
        "openai": OpenAIProvider,
        "deepseek": DeepSeekProvider,
        "ollama": OllamaProvider,
    }
    if config["provider"] == "disabled":
        return None
    if config["provider"] not in classes:
        raise ValueError("不支持的 LLM provider")
    return classes[config["provider"]](config["model"], config.get("timeout", 60))
