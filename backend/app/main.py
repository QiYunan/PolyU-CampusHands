"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import database_url as default_database_url
from app.database import initialize_database, make_engine, make_session_factory
from app.routes import router


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url or default_database_url())

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        initialize_database(engine)
        try:
            yield
        finally:
            engine.dispose()

    application = FastAPI(title="CampusHands API", lifespan=lifespan)
    application.state.session_factory = make_session_factory(engine)
    application.include_router(router)
    return application


app = create_app()
