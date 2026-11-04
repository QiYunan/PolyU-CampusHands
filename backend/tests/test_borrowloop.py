"""Milestone 02 acceptance and regression checks."""

from datetime import datetime, timedelta, timezone
import time

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import Session

from app.database import initialize_database, make_engine
from app.main import create_app
from app.models import AgentEvent, HelpOffer, HelpRequest, User, UserItem
from app.seed import seed_demo_people, seed_demo_request
from app.services import accept_offer, advance_due, cancel_request, start_search


def request_payload(minutes=20):
    return {
        "item_type": "scientific_calculator",
        "location": "VA",
        "deadline": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
    }


def helper_headers(user_id):
    return {"X-Demo-User-Id": str(user_id)}


def prepare_client(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'demo.db').as_posix()}")
    return app


def test_seed_is_repeatable_and_preserves_existing_requests(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'seed.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as session:
        original = HelpRequest(requester_id=1, category="borrow", item_type="umbrella", location="VA", deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1), status="draft")
        session.add(original)
        session.commit()
        original_id = original.id
    with Session(engine) as session:
        seed_demo_people(session)
        demo = seed_demo_request(session)
        demo_id = demo.id
        seed_demo_people(session)
        assert seed_demo_request(session).id == demo_id
        assert session.get(HelpRequest, original_id).item_type == "umbrella"
        assert session.scalar(select(func.count()).select_from(User)) == 4
        assert session.scalar(select(func.count()).select_from(UserItem)) == 3
        assert session.scalar(select(func.count()).select_from(HelpRequest)) == 2
        assert session.scalar(select(func.count()).select_from(HelpOffer)) == 0
    engine.dispose()


def test_existing_milestone_01_database_adds_tables_without_changing_request(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    User.__table__.create(engine)
    HelpRequest.__table__.create(engine)
    with Session(engine) as session:
        session.add(User(id=1, display_name="Alice", campus_building="VA", availability_status="unknown"))
        session.add(HelpRequest(requester_id=1, category="borrow", item_type="umbrella", location="VA", deadline=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1), status="draft"))
        session.commit()
    initialize_database(engine)
    with Session(engine) as session:
        assert session.get(HelpRequest, 1).status == "draft"
        assert session.get(HelpRequest, 1).item_type == "umbrella"
        assert session.scalar(select(func.count()).select_from(User)) == 1
    assert {"users", "help_requests", "user_items", "help_offers", "agent_events"} <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_decline_then_accept_and_two_confirmations(tmp_path):
    app = prepare_client(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        created = client.post("/api/requests", json=request_payload())
        assert created.status_code == 201 and created.json()["status"] == "draft"
        request_id = created.json()["id"]
        started = client.post(f"/api/requests/{request_id}/search")
        assert started.status_code == 200 and started.json()["status"] == "awaiting_response"
        assert client.post(f"/api/requests/{request_id}/search").status_code == 200
        bob = client.get("/api/helpers/2/offers", headers=helper_headers(2)).json()
        assert len(bob) == 1 and bob[0]["status"] == "pending"
        assert client.get("/api/helpers/3/offers", headers=helper_headers(3)).json() == []
        bob_id = bob[0]["id"]
        assert client.post(f"/api/offers/{bob_id}/decline", headers=helper_headers(2)).status_code == 200
        assert client.post(f"/api/offers/{bob_id}/decline", headers=helper_headers(2)).status_code == 200
        carol = client.get("/api/helpers/3/offers", headers=helper_headers(3)).json()
        assert len(carol) == 1 and carol[0]["status"] == "pending"
        carol_id = carol[0]["id"]
        accepted = client.post(f"/api/offers/{carol_id}/accept", headers=helper_headers(3))
        assert accepted.status_code == 200 and accepted.json()["status"] == "accepted"
        assert client.post(f"/api/offers/{carol_id}/accept", headers=helper_headers(3)).status_code == 200
        matched = client.get(f"/api/requests/{request_id}").json()
        assert matched["status"] == "matched" and matched["matched_helper"] == "Carol"
        assert matched["handoff_location"] == "VA"
        assert client.post(f"/api/requests/{request_id}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{request_id}/complete").json()["status"] == "in_progress"
        assert client.post(f"/api/offers/{carol_id}/confirm-completion", headers=helper_headers(3)).json()["request_status"] == "completed"
        completed = client.get(f"/api/requests/{request_id}").json()
        assert completed["status"] == "completed"
        assert completed["requester_confirmed"] and completed["helper_confirmed"]
        assert [event["event_type"] for event in completed["events"]].count("offer_sent") == 2
        assert client.post(f"/api/requests/{request_id}/cancel").status_code == 409
        assert client.post(f"/api/offers/{bob_id}/accept", headers=helper_headers(2)).status_code == 409
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer)) == 2
            assert session.get(UserItem, 2).available is False


def test_timeout_checks_deadline_before_next_helper(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'timeout.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as session:
        seed_demo_people(session)
        now = datetime.now(timezone.utc)
        request = HelpRequest(requester_id=1, category="borrow", item_type="scientific_calculator", location="VA", deadline=(now + timedelta(seconds=20)).replace(tzinfo=None), status="draft")
        session.add(request)
        session.commit()
        request_id = request.id
    with Session(engine) as session:
        start_search(session, request_id, 1, now)
    with Session(engine) as session:
        advance_due(session, now + timedelta(seconds=21))
    with Session(engine) as session:
        advance_due(session, now + timedelta(seconds=22))
        assert session.get(HelpRequest, request_id).status == "expired"
        offers = session.scalars(select(HelpOffer).where(HelpOffer.request_id == request_id)).all()
        assert len(offers) == 1 and offers[0].helper_id == 2 and offers[0].status == "expired"
        events = session.scalars(select(AgentEvent).where(AgentEvent.request_id == request_id, AgentEvent.event_type == "offer_expired")).all()
        assert len(events) == 1
    engine.dispose()


def test_timeout_contacts_carol_once_and_never_recontacts_bob(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'retry.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as session:
        seed_demo_people(session)
        now = datetime.now(timezone.utc)
        request = HelpRequest(requester_id=1, category="borrow", item_type="scientific_calculator", location="VA", deadline=(now + timedelta(minutes=10)).replace(tzinfo=None), status="draft")
        session.add(request)
        session.commit()
        request_id = request.id
    with Session(engine) as session:
        start_search(session, request_id, 1, now)
    with Session(engine) as session:
        advance_due(session, now + timedelta(seconds=31))
    with Session(engine) as session:
        advance_due(session, now + timedelta(seconds=32))
        offers = session.scalars(select(HelpOffer).where(HelpOffer.request_id == request_id).order_by(HelpOffer.id)).all()
        assert [(offer.helper_id, offer.status) for offer in offers] == [(2, "expired"), (3, "pending")]
    engine.dispose()


def test_matched_cancellation_releases_item_and_deadline_no_longer_expires(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'cancel.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as session:
        seed_demo_people(session)
        now = datetime.now(timezone.utc)
        request = HelpRequest(requester_id=1, category="borrow", item_type="scientific_calculator", location="VA", deadline=(now + timedelta(minutes=1)).replace(tzinfo=None), status="draft")
        session.add(request)
        session.commit()
        request_id = request.id
    with Session(engine) as session:
        start_search(session, request_id, 1, now)
        offer_id = session.scalar(select(HelpOffer.id).where(HelpOffer.request_id == request_id))
    with Session(engine) as session:
        accept_offer(session, offer_id, 2, now + timedelta(seconds=5))
    with Session(engine) as session:
        advance_due(session, now + timedelta(minutes=2))
        assert session.get(HelpRequest, request_id).status == "matched"
    with Session(engine) as session:
        cancel_request(session, request_id, 1)
    with Session(engine) as session:
        assert session.get(UserItem, 1).available is True
        assert session.get(HelpRequest, request_id).status == "cancelled"
    engine.dispose()


def test_helper_permissions_and_timer_stops_on_shutdown(tmp_path):
    app = prepare_client(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=request_payload()).json()["id"]
        client.post(f"/api/requests/{request_id}/search")
        bob_id = client.get("/api/helpers/2/offers", headers=helper_headers(2)).json()[0]["id"]
        assert client.get("/api/helpers/2/offers").status_code == 403
        assert client.get("/api/helpers/2/offers", headers=helper_headers(3)).status_code == 403
        assert client.post(f"/api/offers/{bob_id}/accept", headers=helper_headers(3)).status_code == 403
        assert client.post(f"/api/requests/{request_id}/cancel", headers=helper_headers(2)).status_code == 403
    assert app.state.timeout_task.done()


def test_background_timer_advances_an_overdue_offer_once(tmp_path):
    app = prepare_client(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=request_payload()).json()["id"]
        client.post(f"/api/requests/{request_id}/search")
        with app.state.session_factory() as session:
            bob = session.scalar(select(HelpOffer).where(HelpOffer.request_id == request_id))
            bob.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=1)
            session.commit()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            offers = client.get("/api/helpers/3/offers", headers=helper_headers(3)).json()
            if offers:
                break
            time.sleep(0.1)
        assert len(offers) == 1 and offers[0]["status"] == "pending"
        with app.state.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(HelpOffer).where(HelpOffer.request_id == request_id)) == 2
            assert session.scalar(select(func.count()).select_from(AgentEvent).where(AgentEvent.request_id == request_id, AgentEvent.event_type == "offer_expired")) == 1
    assert app.state.timeout_task.done()
