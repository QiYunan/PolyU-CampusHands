"""Backend-only provider configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values


@dataclass(frozen=True)
class LLMConfig:
    primary: str
    fallback: str
    timeout_seconds: float
    deepseek_key: str | None = field(repr=False)
    deepseek_base_url: str
    deepseek_model: str
    ollama_base_url: str
    ollama_api_key: str = field(repr=False)
    ollama_model: str


def load_config() -> LLMConfig:
    # The real DeepSeek key is deliberately never read from the process environment.
    # Offline tests set both providers to mock and must not load local credentials.
    mock_only = os.environ.get("LLM_PRIMARY_PROVIDER") == os.environ.get("LLM_FALLBACK_PROVIDER") == "mock"
    values = {} if mock_only else dotenv_values(Path(__file__).resolve().parents[2] / ".env")

    def setting(name: str, default: str) -> str:
        return os.environ.get(name, values.get(name) or default)

    return LLMConfig(
        primary=setting("LLM_PRIMARY_PROVIDER", "deepseek"),
        fallback=setting("LLM_FALLBACK_PROVIDER", "ollama"),
        timeout_seconds=float(setting("LLM_TIMEOUT_SECONDS", "15")),
        deepseek_key=values.get("DEEPSEEK_API_KEY") or None,
        deepseek_base_url=setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=setting("DEEPSEEK_MODEL", "deepseek-flash"),
        ollama_base_url=setting("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        ollama_api_key=setting("OLLAMA_API_KEY", "ollama"),
        ollama_model=setting("OLLAMA_MODEL", "qwen3.5:4b"),
    )
