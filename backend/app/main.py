"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.database import database_url as default_database_url
from app.database import initialize_database, make_engine, make_session_factory
from app.routes import router
from app.agent_routes import router as agent_router
from app.providers.config import load_config
from app.providers.deepseek import make_deepseek
from app.providers.ollama import make_ollama
from app.providers.mock import MockLLMProvider
from app.providers.fallback import ProviderRouter
from app.providers.base import LLMUnavailable
from app.agent_tools import InvalidAgentAction
from app.services import Forbidden, NotFound, advance_due
from app.state_machine import StateConflict


logger = logging.getLogger(__name__)


def create_app(database_url: str | None = None, providers: ProviderRouter | None = None) -> FastAPI:
    engine = make_engine(database_url or default_database_url())
    session_factory = make_session_factory(engine)
    if providers is None:
        config = load_config()
        available = {"mock": MockLLMProvider, "deepseek": lambda: make_deepseek(config), "ollama": lambda: make_ollama(config)}
        if config.primary not in available or config.fallback not in available:
            raise ValueError("Unsupported LLM provider configuration")
        providers = ProviderRouter(available[config.primary](), available[config.fallback]())

    def tick() -> None:
        with session_factory() as session:
            advance_due(session)

    async def timeout_loop() -> None:
        while True:
            try:
                tick()
            except Exception as error:
                logger.error("BorrowLoop timeout check failed (%s)", type(error).__name__)
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
            await providers.close()
            engine.dispose()

    application = FastAPI(title="CampusHands API", lifespan=lifespan)
    application.state.session_factory = session_factory
    application.state.provider_router = providers
    application.include_router(router)
    application.include_router(agent_router)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(_request, _error: RequestValidationError):
        # FastAPI's default 422 body includes the rejected input value.
        return JSONResponse(status_code=422, content={"detail": "请求字段无效，请检查输入。"})

    @application.exception_handler(NotFound)
    async def not_found(_request, error: NotFound):
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(Forbidden)
    async def forbidden(_request, error: Forbidden):
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @application.exception_handler(StateConflict)
    async def conflict(_request, error: StateConflict):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @application.exception_handler(LLMUnavailable)
    async def llm_unavailable(_request, _error: LLMUnavailable):
        return JSONResponse(status_code=503, content={"detail": "模型暂不可用，请稍后重试。", "code": "llm_unavailable", "retryable": True})

    @application.exception_handler(InvalidAgentAction)
    async def invalid_agent_action(_request, _error: InvalidAgentAction):
        return JSONResponse(status_code=422, content={"detail": "Agent 动作或参数无效。"})

    return application


app = create_app()
