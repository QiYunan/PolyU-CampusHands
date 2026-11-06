from app.providers.compatible import CompatibleProvider
from app.providers.config import LLMConfig


def make_deepseek(config: LLMConfig) -> CompatibleProvider:
    return CompatibleProvider("deepseek", config.deepseek_base_url, config.deepseek_key, config.deepseek_model, config.timeout_seconds, deepseek=True)
