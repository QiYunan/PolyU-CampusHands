"""Offline checks that credentials never cross public or diagnostic boundaries."""

import asyncio
import logging
import time
import traceback
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError
from pydantic import ValidationError

from app.agent_schemas import ParsedFields
from app.main import create_app
from app.providers.base import LLMUnavailable, ProviderError
from app.providers.compatible import CompatibleProvider
from app.providers.config import load_config
from app.providers.fallback import ProviderRouter


SENTINEL = "TEST_SECRET_MUST_NOT_APPEAR"


def test_config_provider_validation_and_pytest_failure_repr_redact(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
    monkeypatch.setattr("app.providers.config.dotenv_values", lambda _path: {"DEEPSEEK_API_KEY": SENTINEL})
    config = load_config()
    provider = CompatibleProvider("deepseek", "http://127.0.0.1:9/v1", SENTINEL, "test", 1, deepseek=True)
    try:
        assert config.deepseek_key == SENTINEL
        assert SENTINEL not in repr(config) + str(config) + repr(provider) + str(provider)

        with pytest.raises(ValidationError) as invalid:
            ParsedFields.model_validate({"item_type": SENTINEL})
        assert SENTINEL not in repr(invalid.value) + str(invalid.value)

        # Exercise pytest's own assertion rendering without exposing a field value.
        try:
            assert config == "invalid configuration"
        except AssertionError:
            rendered = str(pytest.ExceptionInfo.from_current().getrepr(style="long"))
            assert SENTINEL not in rendered
        else:
            pytest.fail("Expected a diagnostic assertion failure")
    finally:
        asyncio.run(provider.close())


def test_mock_only_configuration_never_reads_local_env(monkeypatch):
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "mock")
    monkeypatch.setattr("app.providers.config.dotenv_values", lambda _path: pytest.fail("Offline mode read local credentials"))
    assert load_config().deepseek_key is None


def test_connection_and_fallback_errors_hide_sdk_details():
    provider = CompatibleProvider("deepseek", "http://127.0.0.1:9/v1", SENTINEL, "test", 1, deepseek=True)
    request = httpx.Request("POST", "http://127.0.0.1:9/v1", headers={"Authorization": f"Bearer {SENTINEL}"})
    provider.client.chat.completions.create = AsyncMock(side_effect=APIConnectionError(message=SENTINEL, request=request))
    try:
        with pytest.raises(ProviderError) as connection:
            asyncio.run(provider._complete(messages=[]))
        assert SENTINEL not in repr(connection.value) + str(connection.value)
        assert SENTINEL not in "".join(traceback.format_exception(connection.value))

        router = ProviderRouter(provider)
        with pytest.raises(LLMUnavailable) as fallback:
            asyncio.run(router.parse("fictional", datetime.now(timezone.utc), {}))
        assert SENTINEL not in repr(fallback.value) + str(fallback.value)
        assert SENTINEL not in "".join(traceback.format_exception(fallback.value))
        assert SENTINEL not in str(router.status())
    finally:
        asyncio.run(provider.close())


def test_status_http_errors_logs_and_public_timeline_hide_secret(tmp_path, monkeypatch, caplog):
    # All business writes below use a disposable SQLite database.
    provider = CompatibleProvider("deepseek", "http://127.0.0.1:9/v1", SENTINEL, "test", 1, deepseek=True)
    provider.client.chat.completions.create = AsyncMock(side_effect=APIConnectionError(
        message=SENTINEL, request=httpx.Request("POST", "http://127.0.0.1:9/v1")))
    app = create_app(f"sqlite:///{(tmp_path / 'redaction.db').as_posix()}", ProviderRouter(provider))
    real_advance_due = __import__("app.main", fromlist=["advance_due"]).advance_due
    calls = 0

    def fail_background_check(session):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise RuntimeError(SENTINEL)
        return real_advance_due(session)

    monkeypatch.setattr("app.main.advance_due", fail_background_check)
    with caplog.at_level(logging.ERROR, logger="app.main"):
        with TestClient(app) as client:
            status = client.get("/api/system/llm-status")
            assert status.status_code == 200 and SENTINEL not in status.text

            invalid = client.post("/api/requests", json={"item_type": SENTINEL})
            assert invalid.status_code == 422 and SENTINEL not in invalid.text

            unavailable = client.post("/api/agent/drafts", json={"raw_text": "虚构借物请求"})
            assert unavailable.status_code == 503 and SENTINEL not in unavailable.text

            deadline = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
            created = client.post("/api/requests", json={"item_type": "scientific_calculator", "location": "VA", "deadline": deadline})
            assert created.status_code == 201
            request_id = created.json()["id"]
            assert client.post(f"/api/requests/{request_id}/search").status_code == 200
            timeline = client.get(f"/api/requests/{request_id}")
            assert timeline.status_code == 200 and timeline.json()["events"]
            assert SENTINEL not in timeline.text
            time.sleep(1.1)
    assert calls > 1
    assert SENTINEL not in caplog.text
