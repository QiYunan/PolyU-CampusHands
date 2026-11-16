"""Offline checks for the M06 extraction and model-to-service boundary."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.agent_schemas import ActionProposal
from app.agent_tools import validate_action
from app.main import create_app
from app.models import HelpOffer
from app.providers.base import ProviderError
from app.providers.compatible import CompatibleProvider, tool_schemas
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.seed import seed_demo_people


def _app(tmp_path, provider=None):
    return create_app(f"sqlite:///{(tmp_path / 'agent-m06.db').as_posix()}", ProviderRouter(provider or MockLLMProvider()))


def _confirm_payload(draft, **changes):
    payload = {
        "category": draft["category"], "need_summary": draft["need_summary"],
        "item_type": draft["item_type"], "preferred_brand": draft["preferred_brand"],
        "preferred_model": draft["preferred_model"], "substitution_policy": draft["substitution_policy"],
        "location": draft["location"], "deadline": draft["deadline"],
        "urgency": draft["urgency"] or "normal",
    }
    return {**payload, **changes}


def test_mock_original_sentence_carries_casio_and_z_into_request(tmp_path):
    app = _app(tmp_path)
    before = datetime.now(timezone.utc)
    with TestClient(app) as client:
        draft = client.post("/api/agent/drafts", json={"raw_text": "30分钟之后，在Z栋交接，需要一台Casio计算器"})
        assert draft.status_code == 201, draft.text
        body = draft.json()
        assert body["status"] == "ready"
        assert body["category"] == "borrow"
        assert "Casio" in body["need_summary"]
        assert body["item_type"] == "scientific_calculator"
        assert body["location"] == "Z"
        assert body["preferred_brand"] == "Casio"
        assert body["substitution_policy"] == "ask_before_substitute"
        assert before + timedelta(minutes=29) <= datetime.fromisoformat(body["deadline"]) <= datetime.now(timezone.utc) + timedelta(minutes=31)
        confirmed = client.post(f"/api/agent/drafts/{body['id']}/confirm", json=_confirm_payload(body))
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["preferred_brand"] == "Casio"
        assert confirmed.json()["substitution_policy"] == "ask_before_substitute"


def test_unknown_place_stays_in_clarification_until_corrected(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        draft = client.post("/api/agent/drafts", json={"raw_text": "30分钟之后，在火星楼交接，需要科学计算器"})
        assert draft.status_code == 201, draft.text
        body = draft.json()
        assert body["status"] == "collecting_details"
        assert body["matching_issue"] == "unknown_location"
        assert body["missing_fields"] == ["location"]
        assert client.post(f"/api/agent/drafts/{body['id']}/confirm", json=_confirm_payload(body)).status_code == 409
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
        corrected = client.patch(f"/api/agent/drafts/{body['id']}", json={"location": "Z座"})
        assert corrected.status_code == 200
        assert corrected.json()["status"] == "ready"
        assert corrected.json()["matching_issue"] is None
        corrected_body = corrected.json()
        confirmed = client.post(f"/api/agent/drafts/{body['id']}/confirm", json=_confirm_payload(corrected_body))
        assert confirmed.status_code == 200
        assert confirmed.json()["location"] == "Z"


def test_mock_parses_service_and_unknown_borrow_without_calculator_fallback(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        service = client.post("/api/agent/drafts", json={"raw_text": "20分钟后，在Z栋，需要同学帮我搬运实验器材，有偿"})
        assert service.status_code == 201, service.text
        service_body = service.json()
        assert service_body["category"] == "service"
        assert service_body["item_type"] == "other"
        assert service_body["need_summary"] == "有偿帮忙搬运实验器材"
        assert "科学计算器" not in service.text
        created = client.post(f"/api/agent/drafts/{service_body['id']}/confirm", json=_confirm_payload(service_body))
        assert created.status_code == 200, created.text
        assert created.json()["category"] == "service"
        assert created.json()["item_type"] == "other"

        unknown = client.post("/api/agent/drafts", json={"raw_text": "30分钟后，在VA，想借一台显微镜"})
        assert unknown.status_code == 201, unknown.text
        assert unknown.json()["category"] == "borrow"
        assert unknown.json()["item_type"] == "other"
        assert "显微镜" in unknown.json()["need_summary"]


def test_publish_tool_has_only_request_id_and_observation_is_private(tmp_path):
    parameters = tool_schemas(["publish_request"])[0]["function"]["parameters"]
    assert parameters["properties"] == {"request_id": {"type": "integer", "minimum": 1}}
    for extra in ("helper_id", "item_id", "message"):
        with pytest.raises(ValueError):
            validate_action(ActionProposal(name="publish_request", arguments={"request_id": 1, extra: 2}), ["publish_request"], 1)
    with pytest.raises(ValueError):
        ActionProposal(name="send_help_offer", arguments={"request_id": 1})

    class CapturingMock(MockLLMProvider):
        def __init__(self):
            self.observations = []

        async def choose(self, observation, allowed):
            self.observations.append(observation.copy())
            return await super().choose(observation, allowed)

    provider = CapturingMock()
    app = _app(tmp_path, provider)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = client.post("/api/requests", json={"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()})
        assert request.status_code == 201, request.text
        result = client.post(f"/api/agent/requests/{request.json()['id']}/search")
        assert result.status_code == 200, result.text
    assert provider.observations
    assert all(set(observation) == {"request_id", "status", "matching_issue"} for observation in provider.observations)


def test_agent_publication_never_creates_or_selects_a_substitute(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = client.post("/api/requests", json={"item_type": "scientific_calculator", "location": "Z",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "preferred_brand": "Sharp"})
        assert request.status_code == 201, request.text
        request_id = request.json()["id"]
        result = client.post(f"/api/agent/requests/{request_id}/search")
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "awaiting_response"
        assert result.json()["matching_issue"] is None
        assert result.json()["validated_actions"] == ["publish_request"]
        retried = client.post(f"/api/agent/requests/{request_id}/search")
        assert retried.status_code == 200
        assert retried.json()["action_committed"] is False
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0


def test_compatible_provider_rejects_invented_brand_and_corrects_unknown_place():
    provider = CompatibleProvider("test", "http://localhost:1/v1", "dummy", "local", 1)

    def response(fields):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(fields)))])

    base = {"category": "borrow", "need_summary": "Casio 科学计算器", "item_type": "scientific_calculator", "location": "Z", "deadline_in_minutes": 30, "deadline_at": None,
            "urgency": "normal", "preferred_brand": "Casio", "preferred_model": None, "substitution_policy": None}
    provider._complete = AsyncMock(return_value=response(base))
    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.parse("30分钟之后，在Z栋交接，需要科学计算器", datetime.now(timezone.utc), {}))
    assert error.value.code == "invalid_output"

    provider._complete = AsyncMock(return_value=response({**base, "preferred_brand": None}))
    parsed = asyncio.run(provider.parse("30分钟之后，在火星楼交接，需要科学计算器", datetime.now(timezone.utc), {}))
    assert parsed.location == "火星楼"
    assert parsed.deadline_in_minutes == 30

    provider._complete = AsyncMock(return_value=response({**base, "deadline_in_minutes": None}))
    grounded = asyncio.run(provider.parse("30分钟之后，在Z座交接，需要一台卡西歐計算器", datetime.now(timezone.utc), {}))
    assert grounded.location == "Z"
    assert grounded.preferred_brand == "Casio"
    assert grounded.deadline_in_minutes == 30
    asyncio.run(provider.close())
