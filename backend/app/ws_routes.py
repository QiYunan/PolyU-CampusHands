"""WebSocket transport: authorized notifications, never business commands."""

import ipaddress
import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException

from app.services import Forbidden, NotFound, get_helper_for_actor, get_request_for_actor, list_helper_offers


router = APIRouter()
LOCAL_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000",
}
_LAN_RANGES = tuple(ipaddress.ip_network(network) for network in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
_PUBLIC_DEMO_SUFFIX = ".trycloudflare.com"
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


def configured_lan_origins() -> tuple[str, ...]:
    """Accept only explicitly named classroom IPv4 origins on the Vite port."""
    configured: set[str] = set()
    for entry in os.getenv("CAMPUSHANDS_LAN_ORIGINS", "").split(","):
        origin = entry.strip()
        if not origin:
            continue
        parsed = urlsplit(origin)
        try:
            address = ipaddress.IPv4Address(parsed.hostname or "")
            valid = (parsed.scheme == "http" and parsed.port == 5173 and
                     not parsed.username and not parsed.password and
                     not parsed.path and not parsed.query and not parsed.fragment and
                     any(address in network for network in _LAN_RANGES) and
                     origin == f"http://{address}:5173")
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError("CAMPUSHANDS_LAN_ORIGINS must contain explicit RFC1918 http://IP:5173 origins")
        configured.add(origin)
    return tuple(sorted(configured))


def _valid_public_demo_hostname(hostname: str) -> bool:
    if len(hostname) > 253 or not hostname.endswith(_PUBLIC_DEMO_SUFFIX):
        return False
    prefix = hostname.removesuffix(_PUBLIC_DEMO_SUFFIX)
    return bool(prefix) and all(_DNS_LABEL.fullmatch(label) for label in hostname.split("."))


def parse_public_demo_origins(raw: str) -> tuple[str, ...]:
    """Parse canonical, explicit HTTPS TryCloudflare origins only."""
    if not raw.strip():
        return ()
    configured: set[str] = set()
    for entry in raw.split(","):
        origin = entry.strip()
        if not origin:
            raise ValueError(
                "CAMPUSHANDS_PUBLIC_DEMO_ORIGINS must not contain empty entries"
            )
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname or ""
            port = parsed.port
            valid = (
                parsed.scheme == "https"
                and port is None
                and not parsed.username
                and not parsed.password
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and _valid_public_demo_hostname(hostname)
                and origin == f"https://{hostname}"
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError(
                "CAMPUSHANDS_PUBLIC_DEMO_ORIGINS must contain canonical explicit "
                "https://<subdomain>.trycloudflare.com origins using implicit port 443"
            )
        configured.add(origin)
    return tuple(sorted(configured))


def configured_public_demo_origins() -> tuple[str, ...]:
    return parse_public_demo_origins(
        os.getenv("CAMPUSHANDS_PUBLIC_DEMO_ORIGINS", "")
    )


def allowed_websocket_origins(
    public_origins: tuple[str, ...] | None = None,
) -> set[str]:
    public = (
        configured_public_demo_origins()
        if public_origins is None
        else public_origins
    )
    return LOCAL_ORIGINS.union(configured_lan_origins(), public)


def _actor(socket: WebSocket) -> int:
    try:
        public_origins = getattr(socket.app.state, "public_demo_origins", None)
        origins = allowed_websocket_origins(public_origins)
    except ValueError:
        raise WebSocketException(code=1008) from None
    if socket.headers.get("origin") not in origins:
        raise WebSocketException(code=1008)
    raw = socket.query_params.get("demo_user_id")
    try:
        actor_id = int(raw) if raw is not None else 0
    except ValueError:
        actor_id = 0
    if actor_id <= 0:
        raise WebSocketException(code=1008)
    return actor_id


async def _listen(socket: WebSocket, resource_kind: str, resource_id: int) -> None:
    connection = await socket.app.state.realtime_manager.connect(socket, resource_kind, resource_id)
    try:
        while True:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # No client message is a business command, including JSON payloads.
            await socket.close(code=1003)
            break
    except WebSocketDisconnect:
        pass
    finally:
        await socket.app.state.realtime_manager.disconnect(connection)


@router.websocket("/ws/requests/{request_id}")
async def request_events(socket: WebSocket, request_id: int) -> None:
    actor_id = _actor(socket)
    try:
        with socket.app.state.session_factory() as session:
            get_request_for_actor(session, request_id, actor_id)
    except (Forbidden, NotFound):
        raise WebSocketException(code=1008) from None
    await _listen(socket, "request", request_id)


@router.websocket("/ws/helpers/{helper_id}/offers")
async def helper_offers(socket: WebSocket, helper_id: int) -> None:
    actor_id = _actor(socket)
    try:
        with socket.app.state.session_factory() as session:
            list_helper_offers(session, helper_id, actor_id)
    except (Forbidden, NotFound):
        raise WebSocketException(code=1008) from None
    await _listen(socket, "helper", helper_id)


@router.websocket("/ws/helper-board")
async def helper_board(socket: WebSocket) -> None:
    actor_id = _actor(socket)
    try:
        with socket.app.state.session_factory() as session:
            get_helper_for_actor(session, actor_id)
    except (Forbidden, NotFound):
        raise WebSocketException(code=1008) from None
    await _listen(socket, "helper_board", actor_id)


@router.websocket("/ws/helpers/{helper_id}/invitations")
async def helper_invitations(socket: WebSocket, helper_id: int) -> None:
    actor_id = _actor(socket)
    if actor_id != helper_id:
        raise WebSocketException(code=1008)
    try:
        with socket.app.state.session_factory() as session:
            get_helper_for_actor(session, actor_id)
    except (Forbidden, NotFound):
        raise WebSocketException(code=1008) from None
    await _listen(socket, "invitation", helper_id)
