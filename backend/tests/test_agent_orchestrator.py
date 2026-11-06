from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent_schemas import ActionProposal
from app.agent_tools import validate_action
from app.main import create_app
from app.models import AgentEvent, HelpOffer
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.providers.base import ProviderError
from app.seed import seed_demo_people


def test_unknown_tool_and_invalid_arguments_are_rejected():
    try:
        ActionProposal(name="execute_sql", arguments={})
        assert False
    except ValueError:
        pass
    for args in ({"request_id": 2}, {"request_id": 1, "helper_id": 2}, {"request_id": "bad"}):
        try:
            validate_action(ActionProposal(name="send_help_offer", arguments=args), ["send_help_offer"], 1)
            assert False
        except ValueError:
            pass


def test_agent_search_wait_is_nonblocking_and_finish_never_completes(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'loop.db').as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        payload = {"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        request_id = client.post("/api/requests", json=payload).json()["id"]
        first = client.post(f"/api/agent/requests/{request_id}/search")
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "awaiting_response"
        assert first.json()["step_count"] == 2
        second = client.post(f"/api/agent/requests/{request_id}/search")
        assert second.status_code == 200 and second.json()["status"] == "awaiting_response"
        bob = client.get("/api/helpers/2/offers", headers={"X-Demo-User-Id": "2"}).json()
        assert len(bob) == 1 and bob[0]["message"]
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 1
            assert session.scalar(select(func.count()).select_from(AgentEvent).where(AgentEvent.event_type == "request_completed")) == 0
        assert client.post(f"/api/offers/{bob[0]['id']}/decline", headers={"X-Demo-User-Id": "2"}).status_code == 200
        assert len(client.get("/api/helpers/3/offers", headers={"X-Demo-User-Id": "3"}).json()) == 1
        observed = client.post(f"/api/agent/requests/{request_id}/observe")
        assert observed.status_code == 200
        assert observed.json()["status"] == "awaiting_response"
        assert observed.json()["action_committed"] is False
        assert "Carol" in observed.json()["message"]
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 2


def test_failure_after_committed_offer_returns_authoritative_state(tmp_path):
    class FailsAfterOffer(MockLLMProvider):
        def __init__(self):
            self.calls = 0

        async def choose(self, observation, allowed):
            self.calls += 1
            if self.calls > 1:
                raise ProviderError("connection_or_timeout", retryable=False)
            return await super().choose(observation, allowed)

    provider = FailsAfterOffer()
    app = create_app(f"sqlite:///{(tmp_path / 'partial.db').as_posix()}", ProviderRouter(provider))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        payload = {"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        request_id = client.post("/api/requests", json=payload).json()["id"]
        result = client.post(f"/api/agent/requests/{request_id}/search")
        assert result.status_code == 200 and result.json()["action_committed"] is True
        assert result.json()["status"] == "awaiting_response"
        assert client.get(f"/api/requests/{request_id}").json()["status"] == "awaiting_response"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 1


def test_finish_only_stops_loop(tmp_path):
    class Finishes(MockLLMProvider):
        async def choose(self, observation, allowed):
            return ActionProposal(name="finish", arguments={"request_id": observation["request_id"]})

    app = create_app(f"sqlite:///{(tmp_path / 'finish.db').as_posix()}", ProviderRouter(Finishes()))
    with TestClient(app) as client:
        payload = {"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        request_id = client.post("/api/requests", json=payload).json()["id"]
        result = client.post(f"/api/agent/requests/{request_id}/search")
        assert result.status_code == 200 and result.json()["status"] == "draft"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0


def test_wrong_request_id_from_model_is_rejected_without_offer(tmp_path):
    class WrongTarget(MockLLMProvider):
        async def choose(self, observation, allowed):
            return ActionProposal(name="send_help_offer", arguments={"request_id": observation["request_id"] + 1})

    app = create_app(f"sqlite:///{(tmp_path / 'wrong-target.db').as_posix()}", ProviderRouter(WrongTarget()))
    with TestClient(app) as client:
        payload = {"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}
        request_id = client.post("/api/requests", json=payload).json()["id"]
        result = client.post(f"/api/agent/requests/{request_id}/search")
        assert result.status_code == 422
        assert client.get(f"/api/requests/{request_id}").json()["status"] == "draft"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
