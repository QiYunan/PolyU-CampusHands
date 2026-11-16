"""Safe, isolated commands for the fictional classroom demo."""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import initialize_database, make_engine
from app.demo_lock import DemoLockHeld, demo_database_lock
from app.models import AgentEvent, HelpOffer, HelpRequest, HelpRequestDraft, RequestDismissal, User, UserItem
from app.seed import DEMO_HELPERS, seed_demo_people
from app.ws_routes import configured_public_demo_origins, parse_public_demo_origins


DEMO_DIRECTORY = Path(__file__).resolve().parents[1] / ".demo"
DEMO_DATABASE = DEMO_DIRECTORY / "campushands.db"
MARKER_TABLE = "campushands_demo_marker"
MARKER_VALUE = "CampusHands classroom demo database v1"
FRONTEND_DIRECTORY = DEMO_DIRECTORY.parent.parent / "frontend"
REQUIRED_PYTHON = (3, 11)
PYTHON_PACKAGES = ("fastapi", "pydantic", "sqlalchemy", "uvicorn", "wsproto", "openai", "python-dotenv", "pytest", "httpx")
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class DemoError(RuntimeError):
    """A safe, user-facing demo command failure."""


def _assert_target(path: Path) -> None:
    """The public reset command has no path argument or environment override."""
    if path.absolute() != DEMO_DATABASE.absolute():
        raise DemoError("Refusing an unexpected database path")
    if DEMO_DIRECTORY.is_symlink() or path.is_symlink():
        raise DemoError("Refusing a symbolic link in the demo database path")
    if DEMO_DIRECTORY.resolve() != DEMO_DIRECTORY.absolute():
        raise DemoError("Refusing a redirected demo database directory")
    if path.exists() and not path.is_file():
        raise DemoError("Demo database path is not a regular file")


def _has_marker(path: Path) -> bool:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            row = connection.execute(
                f"SELECT value FROM {MARKER_TABLE} WHERE name = ?", ("identity",)
            ).fetchone()
            return row is not None and row[0] == MARKER_VALUE
    except sqlite3.DatabaseError:
        return False


def _backend_is_active() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=0.3):
            return True
    except OSError:
        return False


def reset_demo_database(path: Path | None = None) -> dict[str, int]:
    """Recreate only the marked, fixed demo database. Never loads provider config."""
    path = path if path is not None else DEMO_DATABASE
    _assert_target(path)
    try:
        with demo_database_lock():
            return _reset_unlocked(path)
    except DemoLockHeld as error:
        raise DemoError(str(error)) from None


def _reset_unlocked(path: Path) -> dict[str, int]:
    if _backend_is_active():
        raise DemoError("Port 8000 is active; stop the backend before resetting demo data")
    if path.exists() and not _has_marker(path):
        raise DemoError("Existing demo path is not a marked CampusHands demo database")
    DEMO_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    try:
        initialize_database(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f"CREATE TABLE {MARKER_TABLE} (name TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                f"INSERT INTO {MARKER_TABLE} (name, value) VALUES (?, ?)",
                ("identity", MARKER_VALUE),
            )
        with Session(engine) as session:
            seed_demo_people(session)
            counts = {
                "users": session.scalar(select(func.count()).select_from(User)),
                "items": session.scalar(select(func.count()).select_from(UserItem)),
                "requests": session.scalar(select(func.count()).select_from(HelpRequest)),
                "drafts": session.scalar(select(func.count()).select_from(HelpRequestDraft)),
                "offers": session.scalar(select(func.count()).select_from(HelpOffer)),
                "events": session.scalar(select(func.count()).select_from(AgentEvent)),
                "dismissals": session.scalar(select(func.count()).select_from(RequestDismissal)),
            }
        if counts != {"users": len(DEMO_HELPERS) + 1, "items": len(DEMO_HELPERS), "requests": 0, "drafts": 0, "offers": 0, "events": 0, "dismissals": 0}:
            raise DemoError("Demo seed verification failed")
        return counts
    finally:
        engine.dispose()


def _http_get(url: str, timeout: float = 1.5) -> tuple[int, str]:
    """Probe only documented local services, without inheriting a proxy."""
    from urllib.request import Request

    opener = build_opener(ProxyHandler({}))
    with opener.open(Request(url, headers={"User-Agent": "CampusHands-preflight"}), timeout=timeout) as response:
        return response.status, response.read(65536).decode("utf-8", errors="replace")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _port_owner(port: int) -> str:
    if os.name != "nt":
        return "PID unavailable; inspect the listening process"
    try:
        command = ["powershell", "-NoProfile", "-Command",
                   f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"]
        result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace", timeout=3, check=False)
        pid = result.stdout.strip()
        return f"PID {pid}" if pid.isdecimal() else "PID unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "PID unavailable"


def _demo_baseline_ok() -> bool:
    _assert_target(DEMO_DATABASE)
    if not DEMO_DATABASE.is_file() or not _has_marker(DEMO_DATABASE):
        return False
    try:
        with closing(sqlite3.connect(f"file:{DEMO_DATABASE.as_posix()}?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            people = connection.execute("SELECT id, display_name, campus_building, availability_status, reliability_score FROM users ORDER BY id").fetchall()
            items = connection.execute("SELECT user_id, item_type, item_name, brand, model, available FROM user_items ORDER BY user_id").fetchall()
            counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("help_requests", "help_request_drafts", "help_offers", "agent_events", "request_dismissals")]
            expected_people = [(1, "Alice", "VA", "unknown", None)] + [(row[0], row[1], row[2], row[3], row[4]) for row in DEMO_HELPERS]
            expected_items = [(row[0], row[5], row[6], row[7], row[8], int(row[9])) for row in DEMO_HELPERS]
            return people == expected_people and items == expected_items and \
                counts == [0, 0, 0, 0, 0]
    except sqlite3.DatabaseError:
        return False


def _node_supported(version: str) -> bool:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        return False
    major, minor, _patch = map(int, match.groups())
    return (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major >= 24


def _websocket_ready(host: str = "127.0.0.1", origin: str = "http://127.0.0.1:5173") -> bool:
    # A handshake tests the actual Uvicorn upgrade path without sending commands.
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = ("GET /ws/helper-board?demo_user_id=5 HTTP/1.1\r\n"
               f"Host: {host}:8000\r\n"
               f"Origin: {origin}\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    try:
        with socket.create_connection((host, 8000), timeout=2) as connection:
            connection.settimeout(2)
            connection.sendall(request.encode("ascii"))
            return connection.recv(512).startswith(b"HTTP/1.1 101")
    except OSError:
        return False


def _public_demo_url(value: str) -> tuple[str, str]:
    origins = parse_public_demo_origins(value)
    if len(origins) != 1 or origins[0] != value:
        raise ValueError("--public-url must be one canonical public Demo Origin")
    hostname = urlsplit(value).hostname
    if hostname is None:
        raise ValueError("--public-url must include a hostname")
    return origins[0], hostname


def _configured_vite_public_hosts() -> tuple[str, ...]:
    raw = os.getenv("__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS", "")
    if not raw.strip():
        return ()
    entries = raw.split(",")
    try:
        origins = parse_public_demo_origins(
            ",".join(f"https://{entry.strip()}" for entry in entries)
        )
    except ValueError as error:
        raise ValueError(
            "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS must contain explicit lowercase "
            "<subdomain>.trycloudflare.com hostnames without scheme, path, port, or wildcard"
        ) from error
    return tuple(sorted(urlsplit(origin).hostname or "" for origin in origins))


def _public_websocket_ready(origin: str) -> bool:
    """Perform a certificate-verified TLS/SNI WebSocket upgrade through Vite."""
    hostname = urlsplit(origin).hostname
    if hostname is None:
        return False
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected_accept = base64.b64encode(
        hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()
    ).decode("ascii")
    request = (
        "GET /ws/helper-board?demo_user_id=5 HTTP/1.1\r\n"
        f"Host: {hostname}\r\n"
        f"Origin: {origin}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "User-Agent: CampusHands-preflight\r\n\r\n"
    )
    try:
        context = ssl.create_default_context()
        with socket.create_connection((hostname, 443), timeout=5) as connection:
            with context.wrap_socket(connection, server_hostname=hostname) as secure:
                secure.settimeout(5)
                secure.sendall(request.encode("ascii"))
                response = bytearray()
                while b"\r\n\r\n" not in response and len(response) < 65536:
                    chunk = secure.recv(4096)
                    if not chunk:
                        break
                    response.extend(chunk)
        header_text = bytes(response).split(b"\r\n\r\n", 1)[0].decode(
            "latin-1", errors="replace"
        )
        lines = header_text.split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        connection_tokens = {
            token.strip().lower()
            for token in headers.get("connection", "").split(",")
        }
        return (
            bool(lines)
            and lines[0].startswith("HTTP/1.1 101")
            and headers.get("upgrade", "").lower() == "websocket"
            and "upgrade" in connection_tokens
            and headers.get("sec-websocket-accept") == expected_accept
        )
    except (OSError, ssl.SSLError, ValueError):
        return False


def preflight(stage: str, mode: str, public_url: str | None = None) -> int:
    failures = 0

    def report(level: str, name: str, detail: str) -> None:
        nonlocal failures
        print(f"{level}: {name}: {detail}")
        if level == "FAIL":
            failures += 1

    from app.ws_routes import configured_lan_origins
    try:
        lan_origins = configured_lan_origins()
    except ValueError as error:
        lan_origins = ()
        report("FAIL", "LAN origins", str(error))
    report("PASS", "access URL", "http://127.0.0.1:5173 (local Demo)")
    for origin in lan_origins:
        report("PASS", "classroom LAN URL", origin)

    public_origin: str | None = None
    public_hostname: str | None = None
    public_configuration_ok = public_url is None
    if public_url is not None:
        public_configuration_ok = True
        if mode != "mock":
            report("FAIL", "public provider mode", "public Demo preflight requires --mode mock")
            public_configuration_ok = False
        try:
            public_origin, public_hostname = _public_demo_url(public_url)
            report("PASS", "public Demo URL", public_origin)
        except ValueError as error:
            report("FAIL", "public Demo URL", str(error))
            public_configuration_ok = False
        try:
            public_origins = configured_public_demo_origins()
        except ValueError as error:
            public_origins = ()
            report("FAIL", "public Demo origins", str(error))
            public_configuration_ok = False
        if public_origin is not None:
            origin_matches = public_origin in public_origins
            report(
                "PASS" if origin_matches else "FAIL",
                "public Demo origins",
                "contains the exact public URL" if origin_matches
                else "set CAMPUSHANDS_PUBLIC_DEMO_ORIGINS to the exact public URL",
            )
            public_configuration_ok = public_configuration_ok and origin_matches
        try:
            vite_hosts = _configured_vite_public_hosts()
        except ValueError as error:
            vite_hosts = ()
            report("FAIL", "Vite allowed hosts", str(error))
            public_configuration_ok = False
        backend_hosts = tuple(sorted(
            urlsplit(origin).hostname or "" for origin in public_origins
        ))
        hosts_match = bool(vite_hosts) and vite_hosts == backend_hosts
        report(
            "PASS" if hosts_match else "FAIL",
            "Vite allowed hosts",
            "matches every configured public Demo hostname" if hosts_match
            else "set __VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS to the matching exact hostname list",
        )
        public_configuration_ok = public_configuration_ok and hosts_match
        if public_hostname is not None:
            current_host_allowed = public_hostname in vite_hosts
            report(
                "PASS" if current_host_allowed else "FAIL",
                "current Vite hostname",
                public_hostname if current_host_allowed else "public URL hostname is not explicitly allowed",
            )
            public_configuration_ok = public_configuration_ok and current_host_allowed

    report("PASS" if sys.version_info[:2] >= REQUIRED_PYTHON else "FAIL", "Python",
           f"{sys.version_info.major}.{sys.version_info.minor}; requires 3.11+")
    missing = []
    for package in PYTHON_PACKAGES:
        try:
            importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package)
    report("FAIL" if missing else "PASS", "backend dependencies",
           "run pip install -e .[dev]" if missing else "installed")

    try:
        node = subprocess.run(["node", "--version"], capture_output=True, encoding="utf-8", errors="replace", timeout=3, check=False)
        node_version = node.stdout.strip()
        node_ok = node.returncode == 0 and _node_supported(node_version)
    except (OSError, subprocess.TimeoutExpired):
        node_version, node_ok = "missing", False
    report("PASS" if node_ok else "FAIL", "Node", f"{node_version}; requires Vite-compatible Node")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if npm is None or not (FRONTEND_DIRECTORY / "package-lock.json").is_file():
        frontend_ok = False
    else:
        try:
            result = subprocess.run([npm, "ls", "--depth=0"], cwd=FRONTEND_DIRECTORY,
                                    capture_output=True, encoding="utf-8", errors="replace", timeout=15, check=False)
            frontend_ok = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            frontend_ok = False
    report("PASS" if frontend_ok else "FAIL", "frontend dependencies",
           "npm ci completed" if frontend_ok else "run npm.cmd ci in frontend")

    database_setting = os.environ.get("DATABASE_URL", "")
    expected = DEMO_DATABASE.resolve()
    try:
        from sqlalchemy.engine import make_url
        configured = make_url(database_setting)
        configured_path = Path(configured.database or "").resolve()
        database_ok = configured.drivername == "sqlite" and configured_path == expected
    except (ValueError, AttributeError, ArgumentError):
        database_ok = False
    report("PASS" if database_ok else "FAIL", "DATABASE_URL",
           "points to the isolated Demo database" if database_ok else "set DATABASE_URL=sqlite:///./.demo/campushands.db from backend")
    try:
        baseline_ok = _demo_baseline_ok()
    except DemoError:
        baseline_ok = False
    report("PASS" if baseline_ok else "FAIL", "Demo database",
           f"fixed marked seed; {len(DEMO_HELPERS) + 1} users, {len(DEMO_HELPERS)} items, no requests" if baseline_ok else "stop backend and run python -m app.demo reset")

    if stage == "setup":
        for port in (8000, 5173):
            active = _port_open(port)
            report("FAIL" if active else "PASS", f"port {port}",
                   f"occupied ({_port_owner(port)}); release it before starting" if active else "free")
        if mode == "real":
            report("WARN" if (DEMO_DIRECTORY.parent / ".env").is_file() else "FAIL", "DeepSeek configuration",
                   "local config file exists; key and availability unverified" if (DEMO_DIRECTORY.parent / ".env").is_file()
                   else "backend/.env absent; configure a key before the real-provider demo")
        else:
            report("PASS", "provider mode", "Mock Recovery Mode selected before timer; no real provider calls")
        if public_url is not None:
            cloudflared = shutil.which("cloudflared")
            report(
                "PASS" if cloudflared else "FAIL",
                "cloudflared",
                cloudflared or "command not found; install it manually before using public Demo mode",
            )
            config_files = [
                Path.home() / ".cloudflared" / name
                for name in ("config.yaml", "config.yml")
            ]
            present_configs = [str(path) for path in config_files if path.is_file()]
            report(
                "WARN" if present_configs else "PASS",
                "Quick Tunnel config",
                "existing config may prevent Quick Tunnel: " + ", ".join(present_configs)
                if present_configs else "no user Quick Tunnel config conflict detected",
            )
    else:
        try:
            code, body = _http_get("http://127.0.0.1:8000/api/system/health")
            health_ok = code == 200 and json.loads(body) == {"status": "ok"}
        except (OSError, URLError, ValueError, AttributeError, TypeError):
            health_ok = False
        report("PASS" if health_ok else "FAIL", "FastAPI health", "database reachable" if health_ok else "start Uvicorn on port 8000")
        try:
            code, body = _http_get("http://127.0.0.1:5173/")
            frontend_ready = code == 200 and "CampusHands" in body
        except (OSError, URLError):
            frontend_ready = False
        report("PASS" if frontend_ready else "FAIL", "frontend port 5173",
               "CampusHands page reachable" if frontend_ready else f"start Vite on port 5173 ({_port_owner(5173)})")
        websocket_ok = _websocket_ready() if health_ok else False
        report("PASS" if websocket_ok else "FAIL", "WebSocket upgrade",
               "Helper board read-only handshake succeeded" if websocket_ok else "start Uvicorn with --ws wsproto")
        for origin in lan_origins:
            host = origin.removeprefix("http://").removesuffix(":5173")
            try:
                lan_frontend = _http_get(origin + "/")[0] == 200
                lan_backend = _http_get(f"http://{host}:8000/api/system/health")[0] == 200
            except (OSError, URLError, ValueError, AttributeError, TypeError):
                lan_frontend = lan_backend = False
            report("PASS" if lan_frontend else "FAIL", "LAN frontend", origin if lan_frontend else f"cannot reach {origin}")
            report("PASS" if lan_backend else "FAIL", "LAN backend", f"http://{host}:8000" if lan_backend else f"cannot reach http://{host}:8000")
            lan_socket = _websocket_ready(host, origin) if lan_backend else False
            report("PASS" if lan_socket else "FAIL", "LAN WebSocket", "Helper board handshake succeeded" if lan_socket else f"cannot upgrade via {origin}")
        if public_url is not None and public_origin is not None:
            if public_configuration_ok:
                try:
                    code, body = _http_get(public_origin + "/", timeout=5)
                    public_frontend = code == 200 and "CampusHands" in body
                except (OSError, URLError, ValueError, AttributeError, TypeError):
                    public_frontend = False
                report(
                    "PASS" if public_frontend else "FAIL",
                    "public HTTPS frontend",
                    public_origin if public_frontend else f"cannot reach {public_origin}",
                )
                try:
                    code, body = _http_get(public_origin + "/api/system/health", timeout=5)
                    public_api = code == 200 and json.loads(body) == {"status": "ok"}
                except (OSError, URLError, ValueError, AttributeError, TypeError):
                    public_api = False
                report(
                    "PASS" if public_api else "FAIL",
                    "public HTTPS API",
                    "same-origin /api proxy reached FastAPI" if public_api
                    else "cannot reach /api/system/health through the public URL",
                )
                public_socket = _public_websocket_ready(public_origin)
                report(
                    "PASS" if public_socket else "FAIL",
                    "public WSS upgrade",
                    "TLS/SNI Helper board handshake succeeded" if public_socket
                    else "cannot upgrade Helper board WSS through the public URL",
                )
            else:
                report("FAIL", "public ready probes", "fix public configuration before network probes")
        try:
            code, body = _http_get("http://127.0.0.1:8000/api/system/llm-status")
            status = json.loads(body) if code == 200 else {}
            expected_providers = ("mock", "mock") if mode == "mock" else ("deepseek", "ollama")
            provider_ok = (status.get("primary"), status.get("fallback")) == expected_providers
            if mode == "real" and status.get("primary_status") == "unconfigured":
                provider_ok = False
            report("PASS" if provider_ok else "FAIL", "provider configuration",
                   f"primary={status.get('primary', 'unknown')} ({status.get('primary_status', 'unknown')}), "
                   f"fallback={status.get('fallback', 'unknown')} ({status.get('fallback_status', 'unknown')}); "
                   + ("Mock Recovery Mode" if mode == "mock" else "unknown means configured but not yet verified by a model call"))
        except (OSError, URLError, ValueError, AttributeError, TypeError):
            report("FAIL", "provider configuration", "status unavailable; check backend")

    if mode == "real" and public_url is None:
        try:
            code, body = _http_get("http://127.0.0.1:11434/api/tags")
            models = json.loads(body).get("models", []) if code == 200 else []
            ollama_ok = any(model.get("name") == "qwen3.5:4b" for model in models)
            detail = "local Ollama running with qwen3.5:4b" if ollama_ok else "run Ollama and pull qwen3.5:4b before timer"
        except (OSError, URLError, ValueError, AttributeError, TypeError):
            ollama_ok, detail = False, "Ollama unavailable at loopback:11434; start it before timer"
        report("PASS" if ollama_ok else "FAIL", "Ollama fallback", detail)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CampusHands classroom demo tools")
    parser.add_argument("command", choices=["reset", "preflight"])
    parser.add_argument("--stage", choices=["setup", "ready"], default="setup")
    parser.add_argument("--mode", choices=["real", "mock"], default="real")
    parser.add_argument("--public-url")
    args = parser.parse_args(argv)
    try:
        if args.command == "reset":
            if args.public_url is not None:
                raise DemoError("--public-url is only valid with preflight")
            counts = reset_demo_database()
            print(f"PASS: reset {DEMO_DATABASE} (users={counts['users']}, items={counts['items']}, requests=0, offers=0)")
            return 0
        return preflight(args.stage, args.mode, args.public_url)
    except (DemoError, OSError, sqlite3.DatabaseError, SQLAlchemyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
