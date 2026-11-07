"""Safe, isolated commands for the fictional classroom demo."""

from __future__ import annotations

import argparse
import base64
import importlib.metadata
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from sqlalchemy import func, select
from sqlalchemy.exc import ArgumentError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import initialize_database, make_engine
from app.demo_lock import DemoLockHeld, demo_database_lock
from app.models import AgentEvent, HelpOffer, HelpRequest, HelpRequestDraft, User, UserItem
from app.seed import seed_demo_people


DEMO_DIRECTORY = Path(__file__).resolve().parents[1] / ".demo"
DEMO_DATABASE = DEMO_DIRECTORY / "campushands.db"
MARKER_TABLE = "campushands_demo_marker"
MARKER_VALUE = "CampusHands classroom demo database v1"
FRONTEND_DIRECTORY = DEMO_DIRECTORY.parent.parent / "frontend"
REQUIRED_PYTHON = (3, 11)
PYTHON_PACKAGES = ("fastapi", "pydantic", "sqlalchemy", "uvicorn", "wsproto", "openai", "python-dotenv", "pytest", "httpx")


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
            }
        if counts != {"users": 4, "items": 3, "requests": 0, "drafts": 0, "offers": 0, "events": 0}:
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
            people = connection.execute("SELECT id, display_name, campus_building, availability_status FROM users ORDER BY id").fetchall()
            items = connection.execute("SELECT user_id, item_type, available FROM user_items ORDER BY user_id").fetchall()
            counts = [connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in ("help_requests", "help_request_drafts", "help_offers", "agent_events")]
            return people == [(1, "Alice", "VA", "unknown"), (2, "Bob", "VA", "available"),
                              (3, "Carol", "PQ", "available"), (4, "David", "Library", "available")] and \
                items == [(2, "scientific_calculator", 1), (3, "scientific_calculator", 1), (4, "charger", 1)] and \
                counts == [0, 0, 0, 0]
    except sqlite3.DatabaseError:
        return False


def _node_supported(version: str) -> bool:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        return False
    major, minor, _patch = map(int, match.groups())
    return (major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major >= 24


def _websocket_ready() -> bool:
    # A handshake tests the actual Uvicorn upgrade path without sending commands.
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = ("GET /ws/helpers/2/offers?demo_user_id=2 HTTP/1.1\r\n"
               "Host: 127.0.0.1:8000\r\n"
               "Origin: http://127.0.0.1:5173\r\n"
               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    try:
        with socket.create_connection(("127.0.0.1", 8000), timeout=2) as connection:
            connection.settimeout(2)
            connection.sendall(request.encode("ascii"))
            return connection.recv(512).startswith(b"HTTP/1.1 101")
    except OSError:
        return False


def preflight(stage: str, mode: str) -> int:
    failures = 0

    def report(level: str, name: str, detail: str) -> None:
        nonlocal failures
        print(f"{level}: {name}: {detail}")
        if level == "FAIL":
            failures += 1

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
           "fixed marked seed; 4 users, 3 items, no requests" if baseline_ok else "stop backend and run python -m app.demo reset")

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
               "Helper read-only handshake succeeded" if websocket_ok else "start Uvicorn with --ws wsproto")
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

    if mode == "real":
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
    args = parser.parse_args(argv)
    try:
        if args.command == "reset":
            counts = reset_demo_database()
            print(f"PASS: reset {DEMO_DATABASE} (users={counts['users']}, items={counts['items']}, requests=0, offers=0)")
            return 0
        return preflight(args.stage, args.mode)
    except (DemoError, OSError, sqlite3.DatabaseError, SQLAlchemyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
