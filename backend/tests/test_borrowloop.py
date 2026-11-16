"""BorrowLoop regression checks for the open Helper board and first valid claim."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import initialize_database, make_engine
from app.main import create_app
from app.models import AgentEvent, HelpOffer, HelpRequest, User, UserItem
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.schemas import ClaimRequest
from app.seed import DEMO_HELPERS, seed_demo_people, seed_demo_request
from app.services import ClaimConflict, advance_due, claim_request


def _app(tmp_path):
    return create_app(f"sqlite:///{(tmp_path / 'borrowloop.db').as_posix()}", ProviderRouter(MockLLMProvider()))


def _payload(minutes=20, location="Z"):
    return {"category": "borrow", "need_summary": "Casio 科学计算器",
            "item_type": "scientific_calculator", "location": location,
            "preferred_brand": "Casio",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()}


def _claim_payload(**overrides):
    return {"capability_confirmed": True, "response_type": "direct",
            "offered_brand": "Casio", **overrides}


def _headers(helper_id):
    return {"X-Demo-User-Id": str(helper_id)}


def test_seed_is_repeatable_and_preserves_existing_requests(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as session:
        session.add(HelpRequest(requester_id=1, item_type="umbrella", location="VA",
            deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1), status="draft"))
        session.commit()
        original_id = session.scalar(select(HelpRequest.id))
        seed_demo_people(session)
        demo_id = seed_demo_request(session).id
        seed_demo_people(session)
        assert seed_demo_request(session).id == demo_id
        assert session.get(HelpRequest, original_id).item_type == "umbrella"
        assert session.scalar(select(func.count()).select_from(User)) == len(DEMO_HELPERS) + 1
        assert session.scalar(select(func.count()).select_from(UserItem)) == len(DEMO_HELPERS)
        assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
    engine.dispose()


def test_publish_dismiss_restore_claim_and_completion(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        roles = client.get("/api/demo/roles").json()
        assert {(role["id"], role["display_name"]) for role in roles} >= {(2, "Bob"), (3, "Carol"), (5, "Erin"), (7, "Grace")}
        request_id = client.post("/api/requests", json=_payload()).json()["id"]
        assert client.post(f"/api/requests/{request_id}/publish").json()["status"] == "awaiting_response"
        assert client.post(f"/api/requests/{request_id}/publish").json()["status"] == "awaiting_response"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
        for actor in (5, 7):
            board = client.get("/api/helper-board", headers=_headers(actor)).json()
            assert board["requests"][0]["id"] == request_id
            assert set(board["viewer"]) == {"id", "display_name"}
        assert client.post(f"/api/requests/{request_id}/dismiss", headers=_headers(5)).json()["requests"] == []
        assert client.get("/api/helper-board", headers=_headers(7)).json()["requests"]
        assert client.post(f"/api/requests/{request_id}/dismiss", headers=_headers(5)).status_code == 200
        assert client.post(f"/api/requests/{request_id}/restore", headers=_headers(5)).json()["requests"]
        assert client.post(f"/api/requests/{request_id}/restore", headers=_headers(5)).status_code == 200
        winner = client.post(f"/api/requests/{request_id}/claim", headers=_headers(5), json=_claim_payload())
        assert winner.status_code == 200 and winner.json()["status"] == "accepted"
        assert client.post(f"/api/requests/{request_id}/claim", headers=_headers(5), json=_claim_payload()).json()["id"] == winner.json()["id"]
        loser = client.post(f"/api/requests/{request_id}/claim", headers=_headers(7), json=_claim_payload())
        assert loser.status_code == 409 and loser.json()["code"] == "already_claimed"
        assert client.get("/api/helper-board", headers=_headers(7)).json()["requests"] == []
        assert client.post(f"/api/requests/{request_id}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{request_id}/complete").json()["status"] == "in_progress"
        assert client.post(f"/api/offers/{winner.json()['id']}/confirm-completion", headers=_headers(5)).json()["request_status"] == "completed"
        view = client.get(f"/api/requests/{request_id}").json()
        assert [event["event_type"] for event in view["events"]] == ["request_published", "request_claimed", "handoff_started", "request_completed"]


def test_two_concurrent_helpers_create_exactly_one_accepted_offer(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=_payload()).json()["id"]
        client.post(f"/api/requests/{request_id}/publish")
        gate = Barrier(2)

        def try_claim(helper_id):
            gate.wait(timeout=5)
            with app.state.session_factory() as session:
                try:
                    response = ClaimRequest.model_validate(_claim_payload())
                    return ("won", claim_request(session, request_id, helper_id, response).helper_id)
                except ClaimConflict:
                    return ("lost", helper_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=10) for future in (
                pool.submit(try_claim, 5), pool.submit(try_claim, 7))]
        assert sorted(outcome for outcome, _ in results) == ["lost", "won"]
        with app.state.session_factory() as session:
            accepted = session.scalars(select(HelpOffer).where(
                HelpOffer.request_id == request_id, HelpOffer.status == "accepted")).all()
            assert len(accepted) == 1
            assert session.get(HelpRequest, request_id).status == "matched"
            assert accepted[0].item_id is None


def test_no_personal_timer_and_cancel_releases_item(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=_payload()).json()["id"]
        client.post(f"/api/requests/{request_id}/publish")
        with app.state.session_factory() as session:
            advance_due(session, datetime.now(timezone.utc) + timedelta(seconds=31))
            assert session.get(HelpRequest, request_id).status == "awaiting_response"
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
        claim = client.post(f"/api/requests/{request_id}/claim", headers=_headers(5), json=_claim_payload()).json()
        assert client.post(f"/api/requests/{request_id}/cancel", headers=_headers(5)).status_code == 403
        assert client.post(f"/api/requests/{request_id}/cancel").json()["status"] == "cancelled"
        with app.state.session_factory() as session:
            cancelled_offer = session.get(HelpOffer, claim["id"])
            assert cancelled_offer.status == "cancelled" and cancelled_offer.item_id is None
            assert session.scalar(select(func.count()).select_from(AgentEvent).where(
                AgentEvent.request_id == request_id, AgentEvent.event_type == "request_cancelled")) == 1
