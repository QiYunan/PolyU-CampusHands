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
    assert first == {"users": 12, "items": 11, "requests": 0, "drafts": 0, "offers": 0, "events": 0, "dismissals": 0}
    engine = make_engine(f"sqlite:///{isolated_demo.as_posix()}")
    try:
        with Session(engine) as session:
            people = session.scalars(select(User).order_by(User.id)).all()
            assert len(people) == 12
            assert [(person.id, person.display_name, person.campus_building) for person in people[:5]] == [
                (1, "Alice", "VA"), (2, "Bob", "VA"), (3, "Carol", "PQ"),
                (4, "David", "L"), (5, "Erin", "Z")
            ]
            items = session.scalars(select(UserItem).order_by(UserItem.user_id)).all()
            assert len(items) == 11
            assert any(item.user_id == 5 and item.brand == "Casio" and item.model == "fx-991EX" for item in items)
            assert any(item.user_id == 7 and item.brand == "Casio" and item.model == "fx-991EX" for item in items)
            assert any(item.user_id == 8 and not item.available for item in items)
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
        assert connection.execute("SELECT COUNT(*) FROM request_dismissals").fetchone()[0] == 0


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


def test_demo_preflight_detects_corrupt_m06_seed(isolated_demo):
    demo.reset_demo_database()
    assert demo._demo_baseline_ok()
    with closing(sqlite3.connect(isolated_demo)) as connection:
        connection.execute("UPDATE user_items SET brand = NULL WHERE user_id = 5")
        connection.commit()
    assert not demo._demo_baseline_ok()
    demo.reset_demo_database()
    with closing(sqlite3.connect(isolated_demo)) as connection:
        connection.execute("UPDATE users SET reliability_score = NULL WHERE id = 5")
        connection.commit()
    assert not demo._demo_baseline_ok()


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


@pytest.mark.parametrize("origin", [
    "http://*:5173", "http://8.8.8.8:5173", "https://192.168.1.4:5173",
    "http://192.168.1.4:8000", "http://192.168.1.4:5173/path",
])
def test_lan_origin_rejects_wildcards_public_hosts_and_wrong_scheme(monkeypatch, origin):
    from app.ws_routes import configured_lan_origins
    monkeypatch.setenv("CAMPUSHANDS_LAN_ORIGINS", origin)
    with pytest.raises(ValueError, match="explicit RFC1918"):
        configured_lan_origins()


def test_public_demo_origins_accept_exact_single_and_multiple_values(monkeypatch):
    from app.ws_routes import configured_public_demo_origins

    monkeypatch.setenv(
        "CAMPUSHANDS_PUBLIC_DEMO_ORIGINS",
        "https://second.trycloudflare.com, https://exact-name.trycloudflare.com,"
        "https://second.trycloudflare.com",
    )
    assert configured_public_demo_origins() == (
        "https://exact-name.trycloudflare.com",
        "https://second.trycloudflare.com",
    )


@pytest.mark.parametrize("origin", [
    "http://exact-name.trycloudflare.com",
    "https://*.trycloudflare.com",
    "https://trycloudflare.com",
    "https://exact-name.trycloudflare.com.evil.example",
    "https://exact-name-trycloudflare.com",
    "https://example.com",
    "https://user:password@exact-name.trycloudflare.com",
    "https://exact-name.trycloudflare.com/",
    "https://exact-name.trycloudflare.com/path",
    "https://exact-name.trycloudflare.com?query=yes",
    "https://exact-name.trycloudflare.com#fragment",
    "https://exact-name.trycloudflare.com:443",
    "https://exact-name.trycloudflare.com:444",
    "HTTPS://exact-name.trycloudflare.com",
    "https://Exact-Name.trycloudflare.com",
    "https://exact-name.trycloudflare.com,",
    "https://exact-name.trycloudflare.com,https://example.com",
])
def test_public_demo_origins_reject_noncanonical_or_broad_values(monkeypatch, origin):
    from app.ws_routes import configured_public_demo_origins

    monkeypatch.setenv("CAMPUSHANDS_PUBLIC_DEMO_ORIGINS", origin)
    with pytest.raises(ValueError, match="CAMPUSHANDS_PUBLIC_DEMO_ORIGINS"):
        configured_public_demo_origins()


def test_invalid_public_demo_origin_fails_application_creation(tmp_path, monkeypatch):
    from app.main import create_app
    from app.providers.fallback import ProviderRouter
    from app.providers.mock import MockLLMProvider

    monkeypatch.setenv(
        "CAMPUSHANDS_PUBLIC_DEMO_ORIGINS",
        "https://exact-name.trycloudflare.com.evil.example",
    )
    with pytest.raises(ValueError, match="CAMPUSHANDS_PUBLIC_DEMO_ORIGINS"):
        create_app(
            f"sqlite:///{(tmp_path / 'invalid-public.db').as_posix()}",
            ProviderRouter(MockLLMProvider()),
        )


def test_preflight_reports_explicit_lan_url_and_probes_both_services(isolated_demo, tmp_path, monkeypatch, capsys):
    demo.reset_demo_database()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{isolated_demo.as_posix()}")
    monkeypatch.setenv("CAMPUSHANDS_LAN_ORIGINS", "http://192.168.43.21:5173")
    monkeypatch.setattr(demo, "FRONTEND_DIRECTORY", tmp_path)
    (tmp_path / "package-lock.json").write_text("{}")
    monkeypatch.setattr(demo.shutil, "which", lambda _name: "npm")
    monkeypatch.setattr(demo.subprocess, "run", lambda command, **_kwargs:
                        SimpleNamespace(returncode=0, stdout="v24.12.0" if command[0] == "node" else ""))
    checked_urls = []

    def local_response(url, _timeout=1.5):
        checked_urls.append(url)
        if url.endswith("/api/system/health"):
            return 200, '{"status":"ok"}'
        if url.endswith("/api/system/llm-status"):
            return 200, '{"primary":"mock","fallback":"mock"}'
        return 200, "<title>CampusHands</title>"

    handshakes = []
    monkeypatch.setattr(demo, "_http_get", local_response)
    monkeypatch.setattr(demo, "_websocket_ready", lambda host="127.0.0.1", origin="http://127.0.0.1:5173": handshakes.append((host, origin)) or True)
    assert demo.preflight("ready", "mock") == 0
    output = capsys.readouterr().out
    assert "http://192.168.43.21:5173" in output
    assert "PASS: LAN WebSocket" in output
    assert "http://192.168.43.21:8000/api/system/health" in checked_urls
    assert ("192.168.43.21", "http://192.168.43.21:5173") in handshakes


def _public_preflight_environment(isolated_demo, tmp_path, monkeypatch):
    demo.reset_demo_database()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{isolated_demo.as_posix()}")
    monkeypatch.setenv(
        "CAMPUSHANDS_PUBLIC_DEMO_ORIGINS",
        "https://exact-name.trycloudflare.com",
    )
    monkeypatch.setenv(
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS",
        "exact-name.trycloudflare.com",
    )
    frontend = tmp_path / "frontend"
    frontend.mkdir(exist_ok=True)
    (frontend / "package-lock.json").write_text("{}")
    monkeypatch.setattr(demo, "FRONTEND_DIRECTORY", frontend)
    monkeypatch.setattr(demo.subprocess, "run", lambda command, **_kwargs:
                        SimpleNamespace(returncode=0, stdout="v24.12.0" if command[0] == "node" else ""))


def test_public_setup_preflight_validates_tools_and_warns_for_user_config(
    isolated_demo, tmp_path, monkeypatch, capsys
):
    _public_preflight_environment(isolated_demo, tmp_path, monkeypatch)
    monkeypatch.setattr(demo, "_port_open", lambda _port: False)
    monkeypatch.setattr(
        demo.shutil,
        "which",
        lambda name: "cloudflared.exe" if name == "cloudflared" else "npm.cmd",
    )
    cloudflared_directory = tmp_path / ".cloudflared"
    cloudflared_directory.mkdir()
    (cloudflared_directory / "config.yaml").write_text("tunnel: unrelated")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with monkeypatch.context() as patch:
        original = Path.read_text
        patch.setattr(Path, "read_text", lambda self, *args, **kwargs:
                      (_ for _ in ()).throw(AssertionError("read .env")) if self.name == ".env"
                      else original(self, *args, **kwargs))
        assert demo.preflight(
            "setup", "mock", "https://exact-name.trycloudflare.com"
        ) == 0
    output = capsys.readouterr().out
    assert "PASS: public Demo URL" in output
    assert "PASS: cloudflared" in output
    assert "WARN: Quick Tunnel config" in output

    monkeypatch.setattr(
        demo.shutil,
        "which",
        lambda name: None if name == "cloudflared" else "npm.cmd",
    )
    assert demo.preflight(
        "setup", "mock", "https://exact-name.trycloudflare.com"
    ) == 1
    assert "FAIL: cloudflared" in capsys.readouterr().out


def test_public_preflight_rejects_mismatched_environment_without_network_probe(
    isolated_demo, tmp_path, monkeypatch, capsys
):
    _public_preflight_environment(isolated_demo, tmp_path, monkeypatch)
    monkeypatch.setenv(
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS",
        "other-name.trycloudflare.com",
    )
    monkeypatch.setattr(demo.shutil, "which", lambda _name: "npm.cmd")
    checked_urls = []

    def local_response(url, _timeout=1.5, **_kwargs):
        checked_urls.append(url)
        assert not url.startswith("https://")
        if url.endswith("/api/system/health"):
            return 200, '{"status":"ok"}'
        if url.endswith("/api/system/llm-status"):
            return 200, '{"primary":"mock","fallback":"mock","primary_status":"unknown","fallback_status":"unknown"}'
        return 200, "<title>CampusHands</title>"

    monkeypatch.setattr(demo, "_http_get", local_response)
    monkeypatch.setattr(demo, "_websocket_ready", lambda: False)
    assert demo.preflight(
        "ready", "mock", "https://exact-name.trycloudflare.com"
    ) == 1
    output = capsys.readouterr().out
    assert "FAIL: Vite allowed hosts" in output
    assert "FAIL: public ready probes" in output
    assert all(not url.startswith("https://") for url in checked_urls)


def test_public_ready_preflight_uses_same_origin_https_api_and_wss(
    isolated_demo, tmp_path, monkeypatch, capsys
):
    _public_preflight_environment(isolated_demo, tmp_path, monkeypatch)
    monkeypatch.setattr(demo.shutil, "which", lambda _name: "npm.cmd")
    checked_urls = []

    def response(url, _timeout=1.5, **_kwargs):
        checked_urls.append(url)
        if url.endswith("/api/system/health"):
            return 200, '{"status":"ok"}'
        if url.endswith("/api/system/llm-status"):
            return 200, '{"primary":"mock","fallback":"mock","primary_status":"unknown","fallback_status":"unknown"}'
        return 200, "<title>CampusHands</title>"

    public_sockets = []
    monkeypatch.setattr(demo, "_http_get", response)
    monkeypatch.setattr(demo, "_websocket_ready", lambda: True)
    monkeypatch.setattr(
        demo,
        "_public_websocket_ready",
        lambda origin: public_sockets.append(origin) or True,
    )
    assert demo.preflight(
        "ready", "mock", "https://exact-name.trycloudflare.com"
    ) == 0
    output = capsys.readouterr().out
    assert "PASS: public HTTPS frontend" in output
    assert "PASS: public HTTPS API" in output
    assert "PASS: public WSS upgrade" in output
    assert "https://exact-name.trycloudflare.com/" in checked_urls
    assert "https://exact-name.trycloudflare.com/api/system/health" in checked_urls
    assert public_sockets == ["https://exact-name.trycloudflare.com"]


def test_public_websocket_probe_uses_tls_sni_origin_and_valid_helper(monkeypatch):
    captured = {}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeSecure(FakeConnection):
        response = b""

        def settimeout(self, timeout):
            captured["secure_timeout"] = timeout

        def sendall(self, payload):
            captured["request"] = payload.decode("ascii")
            key_line = next(
                line for line in captured["request"].split("\r\n")
                if line.startswith("Sec-WebSocket-Key:")
            )
            key = key_line.split(":", 1)[1].strip()
            accept = __import__("base64").b64encode(
                __import__("hashlib").sha1(
                    (key + demo.WEBSOCKET_GUID).encode("ascii")
                ).digest()
            ).decode("ascii")
            self.response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: keep-alive, Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")

        def recv(self, _size):
            response, self.response = self.response, b""
            return response

    secure = FakeSecure()

    class FakeContext:
        def wrap_socket(self, connection, server_hostname):
            captured["wrapped"] = connection
            captured["server_hostname"] = server_hostname
            return secure

    tcp = FakeConnection()
    monkeypatch.setattr(demo.ssl, "create_default_context", lambda: FakeContext())
    monkeypatch.setattr(
        demo.socket,
        "create_connection",
        lambda address, timeout: captured.update(address=address, timeout=timeout) or tcp,
    )

    assert demo._public_websocket_ready(
        "https://exact-name.trycloudflare.com"
    )
    assert captured["address"] == ("exact-name.trycloudflare.com", 443)
    assert captured["server_hostname"] == "exact-name.trycloudflare.com"
    assert "GET /ws/helper-board?demo_user_id=5 HTTP/1.1" in captured["request"]
    assert "Host: exact-name.trycloudflare.com" in captured["request"]
    assert "Origin: https://exact-name.trycloudflare.com" in captured["request"]


def test_mock_demo_covers_agent_open_board_claim_and_two_confirmations(tmp_path):
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
        confirmed = client.post(f"/api/agent/drafts/{parsed['id']}/confirm", json={
            "category": parsed["category"], "need_summary": parsed["need_summary"],
            "item_type": parsed["item_type"], "preferred_brand": parsed["preferred_brand"],
            "preferred_model": parsed["preferred_model"],
            "substitution_policy": parsed["substitution_policy"],
            "location": parsed["location"], "deadline": parsed["deadline"],
            "urgency": parsed["urgency"] or "normal",
        })
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "draft"
        request_id = confirmed.json()["id"]
        run = client.post(f"/api/agent/requests/{request_id}/search")
        assert run.status_code == 200 and run.json()["validated_actions"] == ["publish_request"]
        assert run.json()["provider"] == "mock" and run.json()["action_committed"] is True
        bob_board = client.get("/api/helper-board", headers={"X-Demo-User-Id": "2"}).json()
        carol_board = client.get("/api/helper-board", headers={"X-Demo-User-Id": "3"}).json()
        assert bob_board["requests"][0]["id"] == carol_board["requests"][0]["id"] == request_id
        assert bob_board["requests"][0]["need_summary"] == carol_board["requests"][0]["need_summary"]
        assert client.get("/api/helpers/2/offers", headers={"X-Demo-User-Id": "2"}).json() == []
        assert client.post(f"/api/requests/{request_id}/dismiss", headers={"X-Demo-User-Id": "2"}).status_code == 200
        assert client.get("/api/helper-board", headers={"X-Demo-User-Id": "3"}).json()["requests"]
        claimed = client.post(f"/api/requests/{request_id}/claim", headers={"X-Demo-User-Id": "3"}, json={
            "capability_confirmed": True, "response_type": "direct",
        })
        assert claimed.status_code == 200 and claimed.json()["status"] == "accepted"
        offer_id = claimed.json()["id"]
        assert client.get(f"/api/requests/{request_id}").json()["status"] == "matched"
        assert client.post(f"/api/requests/{request_id}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{request_id}/complete").json()["status"] == "in_progress"
        assert client.post(f"/api/offers/{offer_id}/confirm-completion", headers={"X-Demo-User-Id": "3"}).status_code == 200
        completed = client.get(f"/api/requests/{request_id}").json()
        assert completed["status"] == "completed"
        assert completed["requester_confirmed"] and completed["helper_confirmed"]
        events = completed["events"]
        assert [event["id"] for event in events] == sorted(event["id"] for event in events)
        assert [event["event_type"] for event in events] == [
            "request_parsed", "request_published", "request_claimed", "handoff_started", "request_completed",
        ]
