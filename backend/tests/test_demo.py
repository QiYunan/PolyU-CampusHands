"""The reset may touch only its fixed, explicitly marked demo database."""

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app import demo, demo_lock
from app.database import make_engine
from app.models import AgentEvent, HelpOffer, HelpRequest, HelpRequestDraft, User, UserItem


@pytest.fixture
def isolated_demo(tmp_path, monkeypatch):
    directory = tmp_path / ".demo"
    path = directory / "campushands.db"
    monkeypatch.setattr(demo, "DEMO_DIRECTORY", directory)
    monkeypatch.setattr(demo, "DEMO_DATABASE", path)
    monkeypatch.setattr(demo_lock, "DEMO_DIRECTORY", directory)
    monkeypatch.setattr(demo_lock, "DEMO_DATABASE", path)
    monkeypatch.setattr(demo_lock, "LOCK_FILE", directory / "backend.lock")
    monkeypatch.setattr(demo, "_backend_is_active", lambda: False)
    return path


def test_reset_recreates_only_marked_demo_database(isolated_demo, tmp_path):
    dev = tmp_path / "campushands.db"
    dev.write_bytes(b"normal development database sentinel")
    fake_env = tmp_path / ".env"
    fake_env.write_bytes(b"private configuration sentinel")

    first = demo.reset_demo_database()
    assert first == {"users": 4, "items": 3, "requests": 0, "drafts": 0, "offers": 0, "events": 0}
    engine = make_engine(f"sqlite:///{isolated_demo.as_posix()}")
    try:
        with Session(engine) as session:
            people = session.scalars(select(User).order_by(User.id)).all()
            assert [(person.id, person.display_name, person.campus_building) for person in people] == [
                (1, "Alice", "VA"), (2, "Bob", "VA"), (3, "Carol", "PQ"), (4, "David", "Library")
            ]
            assert [(item.user_id, item.item_type, item.available) for item in session.scalars(select(UserItem).order_by(UserItem.user_id))] == [
                (2, "scientific_calculator", True), (3, "scientific_calculator", True), (4, "charger", True)
            ]
            session.add(HelpRequest(requester_id=1, category="borrow", item_type="scientific_calculator", location="VA",
                                    deadline=__import__("datetime").datetime(2099, 1, 1), status="draft"))
            session.commit()
            assert session.scalar(select(func.count()).select_from(HelpRequest)) == 1
    finally:
        engine.dispose()

    second = demo.reset_demo_database()
    assert second == first
    assert dev.read_bytes() == b"normal development database sentinel"
    assert fake_env.read_bytes() == b"private configuration sentinel"
    with closing(sqlite3.connect(isolated_demo)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM help_requests").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM help_request_drafts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM help_offers").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0] == 0


def test_reset_refuses_unmarked_symlink_unexpected_path_and_active_server(isolated_demo, tmp_path, monkeypatch):
    isolated_demo.parent.mkdir()
    isolated_demo.write_bytes(b"not a marked demo database")
    with pytest.raises(demo.DemoError, match="not a marked"):
        demo.reset_demo_database()
    assert isolated_demo.read_bytes() == b"not a marked demo database"
    isolated_demo.unlink()

    with pytest.raises(demo.DemoError, match="unexpected"):
        demo.reset_demo_database(tmp_path / "other.db")
    other = tmp_path / "other.db"
    other.write_bytes(b"keep me")
    isolated_demo.write_bytes(b"keep me too")
    with monkeypatch.context() as patch:
        original = Path.is_symlink
        patch.setattr(Path, "is_symlink", lambda self: self == isolated_demo or original(self))
        with pytest.raises(demo.DemoError, match="symbolic"):
            demo.reset_demo_database()
    assert other.read_bytes() == b"keep me"
    assert isolated_demo.read_bytes() == b"keep me too"
    isolated_demo.unlink()

    monkeypatch.setattr(demo, "_backend_is_active", lambda: True)
    with pytest.raises(demo.DemoError, match="stop the backend"):
        demo.reset_demo_database()
    assert not isolated_demo.exists()


def test_reset_cli_returns_nonzero_for_unsafe_target(isolated_demo, capsys):
    isolated_demo.parent.mkdir()
    isolated_demo.write_bytes(b"not marked")
    assert demo.main(["reset"]) == 1
    assert "FAIL:" in capsys.readouterr().err


def test_active_demo_backend_holds_lock_even_without_port_8000(isolated_demo):
    from app.main import create_app
    from app.providers.fallback import ProviderRouter
    from app.providers.mock import MockLLMProvider

    demo.reset_demo_database()
    app = create_app(f"sqlite:///{isolated_demo.as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app):
        with pytest.raises(demo.DemoError, match="in use"):
            demo.reset_demo_database()
    assert demo.reset_demo_database()["requests"] == 0


def test_preflight_reports_failure_without_reading_env(isolated_demo, tmp_path, monkeypatch, capsys):
    demo.reset_demo_database()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package-lock.json").write_text("{}")
    monkeypatch.setattr(demo, "FRONTEND_DIRECTORY", frontend)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{isolated_demo.as_posix()}")
    monkeypatch.setattr(demo, "_port_open", lambda _port: False)
    monkeypatch.setattr(demo.shutil, "which", lambda _name: "npm")
    monkeypatch.setattr(demo.subprocess, "run", lambda command, **_kwargs:
                        SimpleNamespace(returncode=0, stdout="v24.12.0" if command[0] == "node" else ""))
    with monkeypatch.context() as patch:
        original = Path.read_text
        patch.setattr(Path, "read_text", lambda self, *args, **kwargs:
                      (_ for _ in ()).throw(AssertionError("read .env")) if self.name == ".env"
                      else original(self, *args, **kwargs))
        assert demo.preflight("setup", "mock") == 0
    output = capsys.readouterr().out
    assert "PASS: Demo database" in output and "Mock Recovery Mode" in output
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./campushands.db")
    assert demo.preflight("setup", "mock") == 1
    assert "FAIL: DATABASE_URL" in capsys.readouterr().out


def test_preflight_node_version_gate():
    assert demo._node_supported("v20.19.0")
    assert demo._node_supported("v22.12.0")
    assert demo._node_supported("v24.12.0")
    assert not demo._node_supported("v20.18.0")
    assert not demo._node_supported("v21.0.0")


def test_ready_preflight_checks_http_websocket_and_provider(isolated_demo, tmp_path, monkeypatch, capsys):
    demo.reset_demo_database()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package-lock.json").write_text("{}")
    monkeypatch.setattr(demo, "FRONTEND_DIRECTORY", frontend)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{isolated_demo.as_posix()}")
    monkeypatch.setattr(demo.shutil, "which", lambda _name: "npm")
    monkeypatch.setattr(demo.subprocess, "run", lambda command, **_kwargs:
                        SimpleNamespace(returncode=0, stdout="v24.12.0" if command[0] == "node" else ""))

    def local_response(url, _timeout=1.5):
        if url.endswith("/api/system/health"):
            return 200, '{"status":"ok"}'
        if url.endswith("/api/system/llm-status"):
            return 200, '{"primary":"mock","fallback":"mock","primary_status":"unknown","fallback_status":"unknown"}'
        return 200, "<title>CampusHands</title>"

    monkeypatch.setattr(demo, "_http_get", local_response)
    monkeypatch.setattr(demo, "_websocket_ready", lambda: True)
    assert demo.preflight("ready", "mock") == 0
    assert "PASS: WebSocket upgrade" in capsys.readouterr().out
    monkeypatch.setattr(demo, "_websocket_ready", lambda: False)
    assert demo.preflight("ready", "mock") == 1
    assert "FAIL: WebSocket upgrade" in capsys.readouterr().out


def test_mock_demo_covers_agent_bob_carol_and_two_confirmations(tmp_path):
    from app.main import create_app
    from app.providers.fallback import ProviderRouter
    from app.providers.mock import MockLLMProvider
    from app.seed import seed_demo_people

    app = create_app(f"sqlite:///{(tmp_path / 'flow.db').as_posix()}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        draft = client.post("/api/agent/drafts", json={
            "raw_text": "我20分钟后在VA考试，想借一部科学计算器"
        })
        assert draft.status_code == 201
        parsed = draft.json()
        assert (parsed["item_type"], parsed["location"], parsed["urgency"], parsed["status"]) == (
            "scientific_calculator", "VA", "high", "ready"
        )
        confirmed = client.post(f"/api/agent/drafts/{parsed['id']}/confirm")
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "draft"
        request_id = confirmed.json()["id"]
        run = client.post(f"/api/agent/requests/{request_id}/search")
        assert run.status_code == 200 and run.json()["validated_actions"] == ["send_help_offer"]
        assert run.json()["provider"] == "mock" and run.json()["action_committed"] is True
        bob = client.get("/api/helpers/2/offers", headers={"X-Demo-User-Id": "2"}).json()
        assert len(bob) == 1 and bob[0]["status"] == "pending"
        assert client.post(f"/api/offers/{bob[0]['id']}/decline", headers={"X-Demo-User-Id": "2"}).status_code == 200
        carol = client.get("/api/helpers/3/offers", headers={"X-Demo-User-Id": "3"}).json()
        assert len(carol) == 1 and carol[0]["status"] == "pending"
        assert client.post(f"/api/offers/{carol[0]['id']}/accept", headers={"X-Demo-User-Id": "3"}).status_code == 200
        assert client.get(f"/api/requests/{request_id}").json()["status"] == "matched"
        assert client.post(f"/api/requests/{request_id}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{request_id}/complete").json()["status"] == "in_progress"
        assert client.post(f"/api/offers/{carol[0]['id']}/confirm-completion", headers={"X-Demo-User-Id": "3"}).status_code == 200
        completed = client.get(f"/api/requests/{request_id}").json()
        assert completed["status"] == "completed"
        assert completed["requester_confirmed"] and completed["helper_confirmed"]
        events = completed["events"]
        assert [event["id"] for event in events] == sorted(event["id"] for event in events)
        assert all("send_help_offer" not in event["public_message"] for event in events)
