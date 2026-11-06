"""Offline realtime transport and committed-event checks."""

import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.websockets import WebSocketDisconnect

from app.database import initialize_database, make_engine, make_session_factory
from app.main import create_app
from app.models import AgentEvent, HelpOffer, HelpRequest
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.realtime import Connection, ConnectionManager, EventScanner
from app.realtime_schemas import RealtimeNotice
from app.schemas import RequestCreate
from app.seed import seed_demo_people
from app.services import advance_due, create_request, start_search


ORIGIN = {"origin": "http://127.0.0.1:5173"}


def payload():
    return {"item_type": "scientific_calculator", "location": "VA", "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()}


class RecordingManager:
    def __init__(self):
        self.notices = []

    def publish(self, kind, resource_id, notice):
        self.notices.append((kind, resource_id, notice))


def test_scanner_reads_only_commits_and_routes_in_global_id_order(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'events.db').as_posix()}")
    initialize_database(engine)
    sessions = make_session_factory(engine)
    manager = RecordingManager()
    scanner = EventScanner(sessions, manager)
    with sessions() as session:
        seed_demo_people(session)
        request = create_request(session, RequestCreate.model_validate(payload()))
        request_id = request.id
    scanner.initialize_cursor()
    with sessions() as writer:
        writer.add(AgentEvent(request_id=request_id, event_type="test_public", public_message="公开测试事件", metadata_json='{"private_config":"TEST_SECRET_MUST_NOT_APPEAR"}', dedupe_key="realtime:uncommitted"))
        writer.flush()
        assert scanner.scan_once() == 0
        writer.commit()
    assert scanner.scan_once() == 1
    with sessions() as session:
        start_search(session, request_id, 1)
    assert scanner.scan_once() == 2
    request_notices = [notice for kind, _, notice in manager.notices if kind == "request"]
    assert [notice.event_id for notice in request_notices] == sorted(notice.event_id for notice in request_notices)
    assert [notice.event_type for notice in request_notices] == ["test_public", "search_started", "offer_sent"]
    assert "TEST_SECRET_MUST_NOT_APPEAR" not in str([notice.model_dump() for notice in request_notices])
    helper_notices = [(helper_id, notice) for kind, helper_id, notice in manager.notices if kind == "helper"]
    assert helper_notices and all(helper_id == 2 for helper_id, _ in helper_notices)
    assert all(notice.public_message == "邀请状态已更新" and notice.resource_kind == "offer" for _, notice in helper_notices)
    assert scanner.cursor == request_notices[-1].event_id
    engine.dispose()


def test_scanner_retries_failed_serialization_and_routing_without_skipping(tmp_path, monkeypatch):
    engine = make_engine(f"sqlite:///{(tmp_path / 'retry.db').as_posix()}")
    initialize_database(engine)
    sessions = make_session_factory(engine)
    manager = RecordingManager()
    scanner = EventScanner(sessions, manager)
    with sessions() as session:
        seed_demo_people(session)
        request = create_request(session, RequestCreate.model_validate(payload()))
        request_id = request.id
    scanner.initialize_cursor()
    with sessions() as session:
        start_search(session, request_id, 1)
    import app.realtime as realtime
    original = realtime.request_notice
    monkeypatch.setattr(realtime, "request_notice", lambda *_args: (_ for _ in ()).throw(ValueError("serialization failed")))
    with pytest.raises(ValueError):
        scanner.scan_once()
    assert scanner.cursor == 0 and manager.notices == []
    monkeypatch.setattr(realtime, "request_notice", original)
    manager.publish = lambda *_args: (_ for _ in ()).throw(RuntimeError("routing failed"))
    with pytest.raises(RuntimeError):
        scanner.scan_once()
    assert scanner.cursor == 0
    with sessions() as session:
        assert session.get(HelpRequest, request_id).status == "awaiting_response"
        assert len(session.scalars(select(HelpOffer).where(HelpOffer.request_id == request_id)).all()) == 1
    manager.publish = lambda kind, resource_id, notice: manager.notices.append((kind, resource_id, notice))
    assert scanner.scan_once() == 2
    assert scanner.cursor == manager.notices[-1][2].event_id
    engine.dispose()


def test_scanner_query_error_preserves_cursor(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'query.db').as_posix()}")
    initialize_database(engine)
    sessions = make_session_factory(engine)
    scanner = EventScanner(sessions, RecordingManager())
    scanner.initialize_cursor()
    original = scanner.sessions

    def broken_sessions():
        raise RuntimeError("database unavailable")

    scanner.sessions = broken_sessions
    with pytest.raises(RuntimeError):
        scanner.scan_once()
    assert scanner.cursor == 0
    scanner.sessions = original
    assert scanner.scan_once() == 0
    engine.dispose()


def test_full_queue_and_failed_sender_affect_only_that_connection(monkeypatch):
    import app.realtime as realtime
    monkeypatch.setattr(realtime, "SEND_TIMEOUT_SECONDS", 0.01)

    class Socket:
        def __init__(self, slow=False, fail=False):
            self.slow = slow
            self.fail = fail
            self.closed = False
            self.sent = []

        async def accept(self):
            return None

        async def send_json(self, value):
            if self.slow:
                await asyncio.sleep(1)
            if self.fail:
                raise RuntimeError("socket failed")
            self.sent.append(value)

        async def close(self, code=1000):
            self.closed = True

    async def scenario():
        manager = ConnectionManager()
        full = Connection(Socket(), "request", 1)
        manager.connections.add(full)
        for _ in range(full.queue.maxsize):
            full.queue.put_nowait({})
        healthy = await manager.connect(Socket(), "request", 1)
        second_healthy = await manager.connect(Socket(), "request", 1)
        slow = await manager.connect(Socket(slow=True), "request", 1)
        failed = await manager.connect(Socket(fail=True), "request", 1)
        frame = RealtimeNotice(event_id=1, event_type="offer_sent", resource_kind="request", resource_id=1,
            status="awaiting_response", public_message="已联系 Bob", created_at=datetime.now(timezone.utc))
        manager.publish("request", 1, frame)
        await asyncio.sleep(0.05)
        assert full not in manager.connections and full.socket.closed
        assert slow not in manager.connections and slow.socket.closed
        assert failed not in manager.connections and failed.socket.closed
        assert healthy in manager.connections and len(healthy.socket.sent) == 1
        assert second_healthy in manager.connections and len(second_healthy.socket.sent) == 1
        await manager.close()
        assert not manager.connections

    asyncio.run(scenario())


def test_websocket_policy_and_client_commands_are_read_only(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'socket.db').as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=payload()).json()["id"]
        for suffix, headers in [
            ("?demo_user_id=1", {"origin": "https://untrusted.example"}),
            ("", ORIGIN),
            ("?demo_user_id=2", ORIGIN),
        ]:
            with pytest.raises(WebSocketDisconnect) as denied:
                with client.websocket_connect(f"/ws/requests/{request_id}{suffix}", headers=headers):
                    pass
            assert denied.value.code == 1008
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/ws/helpers/2/offers?demo_user_id=3", headers=ORIGIN):
                pass
        assert denied.value.code == 1008
        with client.websocket_connect(f"/ws/requests/{request_id}?demo_user_id=1", headers=ORIGIN) as socket:
            socket.send_json({"action": "cancel", "request_id": request_id})
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1003
        assert client.get(f"/api/requests/{request_id}").json()["status"] == "draft"
        with app.state.session_factory() as session:
            assert session.scalars(select(HelpOffer)).all() == []
    assert app.state.realtime_task.done()


def test_background_scanner_delivers_with_bounded_wait(tmp_path):
    app = create_app(f"sqlite:///{(tmp_path / 'background.db').as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=payload()).json()["id"]
        assert client.post(f"/api/requests/{request_id}/search").status_code == 200
        until = time.monotonic() + 2
        while app.state.event_scanner.cursor == 0 and time.monotonic() < until:
            time.sleep(0.02)
        assert app.state.event_scanner.cursor > 0


def test_requester_and_helper_sockets_follow_bob_carol_and_match(tmp_path, monkeypatch):
    # Manual scan_once keeps this integration test independent of timer sleeps.
    monkeypatch.setattr("app.realtime.SCAN_INTERVAL_SECONDS", 60)
    app = create_app(f"sqlite:///{(tmp_path / 'flow.db').as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request_id = client.post("/api/requests", json=payload()).json()["id"]
        with client.websocket_connect(f"/ws/requests/{request_id}?demo_user_id=1", headers=ORIGIN) as alice, \
             client.websocket_connect("/ws/helpers/2/offers?demo_user_id=2", headers=ORIGIN) as bob, \
             client.websocket_connect("/ws/helpers/3/offers?demo_user_id=3", headers=ORIGIN) as carol:
            assert client.post(f"/api/requests/{request_id}/search").status_code == 200
            assert client.portal is not None
            client.portal.call(app.state.event_scanner.scan_once)
            first = [alice.receive_json(), alice.receive_json()]
            assert [notice["event_type"] for notice in first] == ["search_started", "offer_sent"]
            bob_notice = bob.receive_json()
            assert bob_notice["resource_kind"] == "offer" and bob_notice["status"] == "pending"
            assert "api_key" not in str(first + [bob_notice]).lower()
            bob_offer = client.get("/api/helpers/2/offers", headers={"X-Demo-User-Id": "2"}).json()[0]
            assert client.post(f"/api/offers/{bob_offer['id']}/decline", headers={"X-Demo-User-Id": "2"}).status_code == 200
            client.portal.call(app.state.event_scanner.scan_once)
            second = [alice.receive_json(), alice.receive_json()]
            assert [notice["event_type"] for notice in second] == ["offer_declined", "offer_sent"]
            assert first[-1]["event_id"] < second[0]["event_id"] < second[1]["event_id"]
            carol_notice = carol.receive_json()
            assert carol_notice["resource_kind"] == "offer" and carol_notice["status"] == "pending"
            carol_offer = client.get("/api/helpers/3/offers", headers={"X-Demo-User-Id": "3"}).json()[0]
            assert client.post(f"/api/offers/{carol_offer['id']}/accept", headers={"X-Demo-User-Id": "3"}).status_code == 200
            client.portal.call(app.state.event_scanner.scan_once)
            accepted = alice.receive_json()
            assert accepted["event_type"] == "offer_accepted" and accepted["status"] == "matched"
            assert client.get(f"/api/requests/{request_id}").json()["status"] == "matched"


def test_timeout_continues_to_carol_without_agent_or_socket_command(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'timeout-flow.db').as_posix()}")
    initialize_database(engine)
    sessions = make_session_factory(engine)
    manager = RecordingManager()
    scanner = EventScanner(sessions, manager)
    with sessions() as session:
        seed_demo_people(session)
        request = create_request(session, RequestCreate.model_validate(payload()))
        request_id = request.id
    scanner.initialize_cursor()
    now = datetime.now(timezone.utc)
    with sessions() as session:
        start_search(session, request_id, 1, now=now)
    scanner.scan_once()
    with sessions() as session:
        advance_due(session, now + timedelta(seconds=31))
    scanner.scan_once()
    with sessions() as session:
        offers = session.scalars(select(HelpOffer).where(HelpOffer.request_id == request_id).order_by(HelpOffer.id)).all()
        assert [(offer.helper_id, offer.status) for offer in offers] == [(2, "expired"), (3, "pending")]
        assert session.get(HelpRequest, request_id).status == "awaiting_response"
    request_events = [notice.event_type for kind, _, notice in manager.notices if kind == "request"]
    assert request_events[-2:] == ["offer_expired", "offer_sent"]
    assert any(kind == "helper" and helper_id == 3 for kind, helper_id, _ in manager.notices)
    engine.dispose()
