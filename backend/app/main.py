"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.database import database_url as default_database_url
from app.database import initialize_database, make_engine, make_session_factory
from app.routes import router
from app.services import Forbidden, NotFound, advance_due
from app.state_machine import StateConflict


logger = logging.getLogger(__name__)


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url or default_database_url())
    session_factory = make_session_factory(engine)

    def tick() -> None:
        with session_factory() as session:
            advance_due(session)

    async def timeout_loop() -> None:
        while True:
            try:
                tick()
            except Exception:
                logger.exception("BorrowLoop timeout check failed")
            await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        initialize_database(engine)
        tick()  # Recover due work after a process restart.
        task = asyncio.create_task(timeout_loop())
        application.state.timeout_task = task
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            engine.dispose()

    application = FastAPI(title="CampusHands API", lifespan=lifespan)
    application.state.session_factory = session_factory
    application.include_router(router)

    @application.exception_handler(NotFound)
    async def not_found(_request, error: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(Forbidden)
    async def forbidden(_request, error: Forbidden):
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @application.exception_handler(StateConflict)
    async def conflict(_request, error: StateConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    return application


app = create_app()
