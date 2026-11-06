from app.providers.compatible import CompatibleProvider
from app.providers.config import LLMConfig


def make_ollama(config: LLMConfig) -> CompatibleProvider:
    return CompatibleProvider("ollama", config.ollama_base_url, config.ollama_api_key, config.ollama_model, config.timeout_seconds)
