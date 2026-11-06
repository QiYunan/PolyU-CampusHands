"""Single-process WebSocket notifications from committed AgentEvent rows."""

import asyncio
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models import AgentEvent, HelpOffer, HelpRequest
from app.realtime_schemas import RealtimeNotice, offer_notice, request_notice


logger = logging.getLogger(__name__)
SCAN_INTERVAL_SECONDS = 0.25
QUEUE_CAPACITY = 32
SEND_TIMEOUT_SECONDS = 2


@dataclass(eq=False)
class Connection:
    socket: WebSocket
    resource_kind: str
    resource_id: int
    queue: asyncio.Queue[dict] = field(default_factory=lambda: asyncio.Queue(maxsize=QUEUE_CAPACITY))
    writer: asyncio.Task | None = None
    closed: bool = False


class ConnectionManager:
    def __init__(self):
        self.connections: set[Connection] = set()

    async def connect(self, socket: WebSocket, resource_kind: str, resource_id: int) -> Connection:
        await socket.accept()
        connection = Connection(socket, resource_kind, resource_id)
        self.connections.add(connection)
        connection.writer = asyncio.create_task(self._write(connection))
        return connection

    async def _write(self, connection: Connection) -> None:
        try:
            while True:
                payload = await connection.queue.get()
                await asyncio.wait_for(connection.socket.send_json(payload), SEND_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Realtime client send failed")
        finally:
            await self.disconnect(connection, code=1013)

    def publish(self, resource_kind: str, resource_id: int, notice: RealtimeNotice) -> None:
        payload = notice.model_dump(mode="json")
        for connection in tuple(self.connections):
            if connection.closed or (connection.resource_kind, connection.resource_id) != (resource_kind, resource_id):
                continue
            try:
                connection.queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Never let one slow browser hold the global notification cursor.
                self.connections.discard(connection)
                connection.closed = True
                asyncio.create_task(self.disconnect(connection, code=1013))

    async def disconnect(self, connection: Connection, code: int = 1000) -> None:
        self.connections.discard(connection)
        connection.closed = True
        writer = connection.writer
        if writer is not None and writer is not asyncio.current_task() and not writer.done():
            writer.cancel()
            try:
                await writer
            except asyncio.CancelledError:
                pass
        try:
            await asyncio.wait_for(connection.socket.close(code=code), SEND_TIMEOUT_SECONDS)
        except Exception:
            pass

    async def close(self) -> None:
        for connection in tuple(self.connections):
            await self.disconnect(connection, code=1001)


class EventScanner:
    def __init__(self, sessions: sessionmaker[Session], manager: ConnectionManager):
        self.sessions = sessions
        self.manager = manager
        self.cursor = 0

    def initialize_cursor(self) -> None:
        with self.sessions() as session:
            self.cursor = session.scalar(select(func.max(AgentEvent.id))) or 0

    def scan_once(self) -> int:
        """Route committed events in ID order; failed events remain at the cursor."""
        processed = 0
        with self.sessions() as session:
            events = session.scalars(select(AgentEvent).where(AgentEvent.id > self.cursor).order_by(AgentEvent.id).limit(100)).all()
            for event in events:
                request = session.get(HelpRequest, event.request_id)
                if request is None:
                    raise RuntimeError("Realtime event has no request")
                request_frame = request_notice(event, request)
                offers = session.scalars(select(HelpOffer).where(HelpOffer.request_id == request.id).order_by(HelpOffer.id)).all()
                helper_frames = [(offer.helper_id, offer_notice(event, offer)) for offer in offers]
                # All reads and serialization complete before any client receives
                # this event; only per-client failures are isolated by the manager.
                self.manager.publish("request", request.id, request_frame)
                for helper_id, frame in helper_frames:
                    self.manager.publish("helper", helper_id, frame)
                self.cursor = event.id
                processed += 1
        return processed

    async def run(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception as error:
                logger.error("Realtime scan failed (%s)", type(error).__name__)
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
