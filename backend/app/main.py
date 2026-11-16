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
from app.demo_lock import demo_database_lock
from app.routes import router
from app.supply_routes import router as supply_router
from app.agent_routes import router as agent_router
from app.providers.config import load_config
from app.providers.deepseek import make_deepseek
from app.providers.ollama import make_ollama
from app.providers.mock import MockLLMProvider
from app.providers.fallback import ProviderRouter
from app.providers.base import LLMUnavailable
from app.agent_tools import InvalidAgentAction
from app.services import ClaimConflict, Forbidden, InvalidDeadline, NotFound, UnknownLocation, advance_due
from app.supply_services import CandidatesStale, advance_supply_due
from app.state_machine import StateConflict
from app.realtime import ConnectionManager, EventScanner
from app.ws_routes import configured_public_demo_origins, router as ws_router


logger = logging.getLogger(__name__)


def create_app(database_url: str | None = None, providers: ProviderRouter | None = None) -> FastAPI:
    public_demo_origins = configured_public_demo_origins()
    engine = make_engine(database_url or default_database_url())
    session_factory = make_session_factory(engine)
    if providers is None:
        config = load_config()
        available = {"mock": MockLLMProvider, "deepseek": lambda: make_deepseek(config), "ollama": lambda: make_ollama(config)}
        if config.primary not in available or config.fallback not in available:
            raise ValueError("Unsupported LLM provider configuration")
        providers = ProviderRouter(available[config.primary](), available[config.fallback]())
    realtime_manager = ConnectionManager()
    event_scanner = EventScanner(session_factory, realtime_manager)

    def tick() -> None:
        with session_factory() as session:
            advance_supply_due(session)
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
        with demo_database_lock(engine.url.database):
            initialize_database(engine)
            tick()  # Recover due work after a process restart.
            event_scanner.initialize_cursor()  # Connected clients reconcile via GET.
            task = asyncio.create_task(timeout_loop())
            realtime_task = asyncio.create_task(event_scanner.run())
            application.state.timeout_task = task
            application.state.realtime_task = realtime_task
            try:
                yield
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                realtime_task.cancel()
                try:
                    await realtime_task
                except asyncio.CancelledError:
                    pass
                await realtime_manager.close()
                await providers.close()
                engine.dispose()

    application = FastAPI(title="CampusHands API", lifespan=lifespan)
    application.state.session_factory = session_factory
    application.state.provider_router = providers
    application.state.realtime_manager = realtime_manager
    application.state.event_scanner = event_scanner
    application.state.public_demo_origins = public_demo_origins
    application.include_router(router)
    application.include_router(supply_router)
    application.include_router(agent_router)
    application.include_router(ws_router)

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

    @application.exception_handler(ClaimConflict)
    async def already_claimed(_request, _error: ClaimConflict):
        return JSONResponse(status_code=409, content={"detail": "该请求已被其他同学接下", "code": "already_claimed"})

    @application.exception_handler(CandidatesStale)
    async def candidates_stale(_request, _error: CandidatesStale):
        return JSONResponse(
            status_code=409,
            content={"detail": "候选状态已变化，请重新搜索。", "code": "candidates_stale"},
        )

    @application.exception_handler(LLMUnavailable)
    async def llm_unavailable(_request, _error: LLMUnavailable):
        return JSONResponse(status_code=503, content={"detail": "模型暂不可用，请稍后重试。", "code": "llm_unavailable", "retryable": True})

    @application.exception_handler(InvalidAgentAction)
    async def invalid_agent_action(_request, _error: InvalidAgentAction):
        return JSONResponse(status_code=422, content={"detail": "Agent 动作或参数无效。"})

    @application.exception_handler(UnknownLocation)
    async def unknown_location(_request, _error: UnknownLocation):
        return JSONResponse(status_code=422, content={"detail": "请选择主校园内可识别的交接地点。", "code": "unknown_location"})

    @application.exception_handler(InvalidDeadline)
    async def invalid_deadline(_request, _error: InvalidDeadline):
        return JSONResponse(status_code=422, content={"detail": "请填写有效且尚未过去的截止时间。"})

    return application


app = create_app()
