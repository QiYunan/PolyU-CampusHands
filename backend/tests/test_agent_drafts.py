from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.agent_drafts import create_draft
from app.main import create_app
from app.models import HelpOffer, HelpRequest, HelpRequestDraft
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider


def app_for(tmp_path):
    return create_app(f"sqlite:///{(tmp_path / 'agent.db').as_posix()}", ProviderRouter(MockLLMProvider()))


def confirm_payload(draft, **changes):
    payload = {
        "category": draft["category"], "need_summary": draft["need_summary"],
        "item_type": draft["item_type"], "preferred_brand": draft["preferred_brand"],
        "preferred_model": draft["preferred_model"], "substitution_policy": draft["substitution_policy"],
        "location": draft["location"], "deadline": draft["deadline"],
        "urgency": draft["urgency"] or "normal",
    }
    return {**payload, **changes}


def test_mock_parses_relative_time_against_fixed_clock(tmp_path):
    app = app_for(tmp_path)
    now = datetime(2026, 11, 5, 3, 0, tzinfo=timezone.utc)
    with TestClient(app):
        with app.state.session_factory() as session:
            draft = __import__("asyncio").run(create_draft(session, app.state.provider_router,
                "我20分钟后在VA考试，但计算器坏了，想借一部科学计算器。", 1, now))
            assert draft.item_type == "scientific_calculator"
            assert draft.location == "VA"
            assert draft.deadline == now + timedelta(minutes=20)
            assert draft.urgency == "high"
            assert draft.status == "ready"


@pytest.mark.parametrize("time_phrase", ["20分钟后或30分钟后", "大概20分钟后", "稍后"])
def test_ambiguous_time_requires_clarification(tmp_path, time_phrase):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        result = client.post("/api/agent/drafts", json={"raw_text": f"我在VA想借科学计算器，{time_phrase}需要。"})
        assert result.status_code == 201
        assert result.json()["missing_fields"] == ["deadline"]
        assert result.json()["status"] == "collecting_details"
        body = result.json()
        assert client.post(f"/api/agent/drafts/{body['id']}/confirm", json=confirm_payload(body)).status_code == 409
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpRequest)) == 0
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0


def test_ambiguous_clarification_discards_previous_deadline(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        ready = client.post("/api/agent/drafts", json={"raw_text": "我在VA想借科学计算器，20分钟后需要。"})
        assert ready.status_code == 201 and ready.json()["status"] == "ready"
        clarified = client.post(f"/api/agent/drafts/{ready.json()['id']}/clarify", json={"text": "其实大概30分钟后需要"})
        assert clarified.status_code == 200
        assert clarified.json()["deadline"] is None
        assert clarified.json()["missing_fields"] == ["deadline"]
        clarified_body = clarified.json()
        assert client.post(f"/api/agent/drafts/{ready.json()['id']}/confirm", json=confirm_payload(clarified_body)).status_code == 409


@pytest.mark.parametrize("text,missing", [
    ("我想借一部科学计算器。", ["location", "deadline"]),
    ("我在VA想借一部科学计算器。", ["deadline"]),
    ("我20分钟后想借一部科学计算器。", ["location"]),
    ("我20分钟后在VA交接。", ["need_summary"]),
])
def test_missing_fields_never_create_request_or_offer(tmp_path, text, missing):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        result = client.post("/api/agent/drafts", json={"raw_text": text})
        assert result.status_code == 201, result.text
        assert result.json()["missing_fields"] == missing
        assert result.json()["status"] == "collecting_details"
        draft_id = result.json()["id"]
        assert client.get(f"/api/agent/drafts/{draft_id}").json()["missing_fields"] == missing
        assert client.post(f"/api/agent/drafts/{draft_id}/confirm", json=confirm_payload(result.json())).status_code == 409
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpRequest)) == 0
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0


def test_confirm_applies_current_form_atomically_and_is_idempotent(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        draft = client.post("/api/agent/drafts", json={"raw_text": "我想借一部科学计算器。"}).json()
        draft_id = draft["id"]
        clarified = client.post(f"/api/agent/drafts/{draft_id}/clarify", json={"text": "在VA，20分钟后需要"})
        assert clarified.status_code == 200, clarified.text
        assert clarified.json()["status"] == "ready"
        assert clarified.json()["missing_fields"] == []
        form = confirm_payload(clarified.json(), location="PQ", need_summary="Casio fx-991cnx 科学计算器",
                               preferred_brand="Casio", preferred_model="fx-991cnx",
                               substitution_policy="exact_only", urgency="high")
        first = client.post(f"/api/agent/drafts/{draft_id}/confirm", json=form)
        second = client.post(f"/api/agent/drafts/{draft_id}/confirm", json=form)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["status"] == "draft"
        assert first.json()["location"] == "PQ"
        assert first.json()["need_summary"] == "Casio fx-991cnx 科学计算器"
        assert first.json()["preferred_brand"] == "Casio"
        assert first.json()["preferred_model"] == "fx-991cnx"
        assert first.json()["substitution_policy"] == "exact_only"
        assert first.json()["urgency"] == "high"
        assert client.get(f"/api/agent/drafts/{draft_id}").json()["request_id"] == first.json()["id"]
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpRequest)) == 1
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
            assert session.get(HelpRequestDraft, draft_id).status == "confirmed"


def test_demo_identity_and_numeric_data_masking(tmp_path):
    app = app_for(tmp_path)
    with TestClient(app) as client:
        text = "我在VA想借计算器，20分钟后需要，电话是 91234567"
        draft = client.post("/api/agent/drafts", json={"raw_text": text})
        assert draft.status_code == 201
        assert "91234567" not in draft.text
        assert client.get(f"/api/agent/drafts/{draft.json()['id']}", headers={"X-Demo-User-Id": "2"}).status_code == 403
        structured = client.post("/api/requests", json={"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(), "raw_text": text})
        assert structured.status_code == 201
        assert "91234567" not in structured.text
