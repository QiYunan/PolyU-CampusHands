import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent_schemas import ActionProposal, ParsedFields
from app.providers.base import LLMUnavailable, ProviderError
from app.providers.compatible import tool_schemas
from app.providers.compatible import CompatibleProvider
from app.providers.config import load_config
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider


class FakeProvider(MockLLMProvider):
    def __init__(self, name, errors=()):
        self.name = name
        self.errors = list(errors)
        self.calls = 0

    async def parse(self, text, now, known):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return ParsedFields(item_type="scientific_calculator")


@pytest.mark.parametrize("code", ["connection_or_timeout", "rate_limited", "server_error", "invalid_output"])
def test_primary_one_retry_then_fallback(code):
    primary = FakeProvider("deepseek", [ProviderError(code), ProviderError(code)])
    fallback = FakeProvider("ollama")
    router = ProviderRouter(primary, fallback)
    asyncio.run(router.parse("text", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), {}))
    assert primary.calls == 2 and fallback.calls == 1
    assert router.status()["fallback_active"] is True
    assert router.status()["active"] == "ollama"


def test_two_provider_failure_and_no_retry_on_nontransient():
    primary = FakeProvider("deepseek", [ProviderError("provider_rejected", retryable=False)])
    fallback = FakeProvider("ollama", [ProviderError("invalid_output")])
    router = ProviderRouter(primary, fallback)
    with pytest.raises(LLMUnavailable):
        asyncio.run(router.parse("text", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), {}))
    assert primary.calls == fallback.calls == 1
    assert router.status()["active"] is None
    assert router.status()["primary_status"] == "unavailable"
    assert router.status()["fallback_status"] == "unavailable"


def test_allowlisted_native_tool_schema_is_shared():
    schemas = tool_schemas(["send_help_offer", "wait_for_response"])
    assert [entry["function"]["name"] for entry in schemas] == ["send_help_offer", "wait_for_response"]
    assert schemas[0]["function"]["parameters"]["additionalProperties"] is False


def test_native_tool_call_and_validated_json_fallback():
    provider = CompatibleProvider("test", "http://localhost:1/v1", "dummy", "local", 1)
    native = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        tool_calls=[SimpleNamespace(function=SimpleNamespace(name="send_help_offer", arguments='{"request_id": 7}'))], content=None))])
    fallback = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        tool_calls=None, content=json.dumps({"name": "wait_for_response", "arguments": {"request_id": 7}})))])
    provider._complete = AsyncMock(side_effect=[native, fallback])
    first = asyncio.run(provider.choose({"request_id": 7, "status": "draft"}, ["send_help_offer"]))
    second = asyncio.run(provider.choose({"request_id": 7, "status": "awaiting_response"}, ["wait_for_response"]))
    assert first.name == "send_help_offer" and second.name == "wait_for_response"
    assert provider._complete.await_args_list[0].kwargs["tools"][0]["function"]["name"] == "send_help_offer"
    asyncio.run(provider.close())


@pytest.mark.parametrize("content", ["", "not json", '{"item_type":"invalid"}'])
def test_invalid_parse_response_rejected(content):
    provider = CompatibleProvider("test", "http://localhost:1/v1", "dummy", "local", 1)
    provider._complete = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))]))
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.parse("sample", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), {}))
    assert error.value.code == "invalid_output"
    asyncio.run(provider.close())


def test_deepseek_non_thinking_is_explicit_and_key_is_file_only(monkeypatch):
    monkeypatch.setattr("app.providers.config.dotenv_values", lambda _path: {})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "must-not-be-used")
    assert load_config().deepseek_key is None
    provider = CompatibleProvider("deepseek", "http://localhost:1", "dummy", "deepseek-flash", 1, deepseek=True)
    provider.client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[]))
    asyncio.run(provider._complete(messages=[]))
    assert provider.client.chat.completions.create.await_args.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    asyncio.run(provider.close())


def test_ollama_non_thinking_is_explicit():
    provider = CompatibleProvider("ollama", "http://localhost:1/v1", "ollama", "qwen3.5:4b", 1)
    provider.client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[]))
    asyncio.run(provider._complete(messages=[]))
    assert provider.client.chat.completions.create.await_args.kwargs["reasoning_effort"] == "none"
    asyncio.run(provider.close())


def test_ollama_unique_explicit_relative_time_is_revalidated():
    provider = CompatibleProvider("ollama", "http://localhost:1/v1", "ollama", "qwen3.5:4b", 1)
    response = {"category": "borrow", "item_type": "scientific_calculator", "location": "VA", "deadline_in_minutes": None, "deadline_at": None, "urgency": "high"}
    provider._complete = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))]))
    parsed = asyncio.run(provider.parse("我20分钟后在VA考试", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), {}))
    assert parsed.deadline_in_minutes == 20
    assert provider._complete.await_args.kwargs["response_format"]["type"] == "json_schema"
    asyncio.run(provider.close())


@pytest.mark.parametrize("phrase", ["20分钟后或30分钟后", "大概20分钟后", "稍后"])
def test_ambiguous_time_cannot_be_guessed_by_model(phrase):
    provider = CompatibleProvider("ollama", "http://localhost:1/v1", "ollama", "qwen3.5:4b", 1)
    response = {"category": "borrow", "item_type": "scientific_calculator", "location": "VA", "deadline_in_minutes": 20, "deadline_at": None, "urgency": "high"}
    provider._complete = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))]))
    parsed = asyncio.run(provider.parse(f"我在VA，{phrase}需要", __import__("datetime").datetime.now(__import__("datetime").timezone.utc), {}))
    assert parsed.deadline_in_minutes is None and parsed.deadline_at is None
    asyncio.run(provider.close())
