from .openai_provider import OpenAIProvider


class DeepSeekProvider(OpenAIProvider):
    key_name = "DEEPSEEK_API_KEY"
    default_url = "https://api.deepseek.com/v1"
