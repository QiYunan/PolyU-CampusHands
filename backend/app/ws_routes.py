"""WebSocket transport: authorized notifications, never business commands."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException

from app.services import Forbidden, NotFound, get_request_for_actor, list_helper_offers


router = APIRouter()
ALLOWED_ORIGINS = {
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:8000", "http://127.0.0.1:8000",
}


def _actor(socket: WebSocket) -> int:
    if socket.headers.get("origin") not in ALLOWED_ORIGINS:
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
