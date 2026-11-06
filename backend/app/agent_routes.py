"""Agent HTTP transport only; validation and mutations remain in services."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.agent_drafts import clarify_draft, confirm_draft, create_draft, draft_view, edit_draft, _require_draft
from app.agent_orchestrator import run_observation, run_search
from app.agent_schemas import AgentRunRead, DraftClarify, DraftCreate, DraftEdit, DraftRead
from app.routes import demo_actor, get_session
from app.schemas import RequestRead
from app.services import InvalidDeadline, request_view


router = APIRouter(prefix="/api")


def provider_router(request: Request):
    return request.app.state.provider_router


@router.post("/agent/drafts", response_model=DraftRead, status_code=201)
async def new_draft(payload: DraftCreate, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor), providers=Depends(provider_router)):
    try:
        return await create_draft(session, providers, payload.raw_text, actor_id)
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/agent/drafts/{draft_id}", response_model=DraftRead)
def get_draft(draft_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor), providers=Depends(provider_router)):
    return draft_view(_require_draft(session, draft_id, actor_id), providers)


@router.post("/agent/drafts/{draft_id}/clarify", response_model=DraftRead)
async def clarify(draft_id: int, payload: DraftClarify, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor), providers=Depends(provider_router)):
    try:
        return await clarify_draft(session, providers, draft_id, payload.text, actor_id)
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.patch("/agent/drafts/{draft_id}", response_model=DraftRead)
def edit(draft_id: int, payload: DraftEdit, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)):
    try:
        return edit_draft(session, draft_id, payload, actor_id)
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/agent/drafts/{draft_id}/confirm", response_model=RequestRead)
def confirm(draft_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)):
    try:
        return request_view(session, confirm_draft(session, draft_id, actor_id))
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/agent/requests/{request_id}/search", response_model=AgentRunRead)
async def agent_search(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor), providers=Depends(provider_router)):
    return await run_search(session, providers, request_id, actor_id)


@router.post("/agent/requests/{request_id}/observe", response_model=AgentRunRead)
async def agent_observe(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor), providers=Depends(provider_router)):
    return await run_observation(session, providers, request_id, actor_id)


@router.get("/system/llm-status")
def llm_status(providers=Depends(provider_router)):
    return providers.status()
