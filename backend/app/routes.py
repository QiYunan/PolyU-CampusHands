"""HTTP endpoints; business rules live in services.py."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.schemas import OfferRead, RequestCreate, RequestRead
from app.services import (
    InvalidDeadline, accept_offer, cancel_request, confirm_helper, confirm_requester,
    create_request, decline_offer, get_request_for_actor, list_helper_offers,
    request_view, start_handoff, start_search,
)


router = APIRouter(prefix="/api")


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def demo_actor(x_demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id")) -> int:
    return 1 if x_demo_user_id is None else x_demo_user_id


def helper_actor(x_demo_user_id: int | None = Header(default=None, alias="X-Demo-User-Id")) -> int:
    if x_demo_user_id is None:
        raise HTTPException(status_code=403, detail="Choose a helper in Demo Mode")
    return x_demo_user_id


@router.post("/requests", response_model=RequestRead, status_code=status.HTTP_201_CREATED)
def post_request(payload: RequestCreate, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    try:
        record = create_request(session, payload, actor_id)
    except InvalidDeadline as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return request_view(session, record)


@router.get("/requests/{request_id}", response_model=RequestRead)
def read_request(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, get_request_for_actor(session, request_id, actor_id))


@router.post("/requests/{request_id}/search", response_model=RequestRead)
def search_request(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, start_search(session, request_id, actor_id))


@router.post("/requests/{request_id}/cancel", response_model=RequestRead)
def cancel(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, cancel_request(session, request_id, actor_id))


@router.post("/requests/{request_id}/start", response_model=RequestRead)
def start(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, start_handoff(session, request_id, actor_id))


@router.post("/requests/{request_id}/complete", response_model=RequestRead)
def complete(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, confirm_requester(session, request_id, actor_id))


@router.get("/helpers/{helper_id}/offers", response_model=list[OfferRead])
def helper_inbox(helper_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> list[OfferRead]:
    return [OfferRead.from_record(offer) for offer in list_helper_offers(session, helper_id, actor_id)]


@router.post("/offers/{offer_id}/accept", response_model=OfferRead)
def accept(offer_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> OfferRead:
    return OfferRead.from_record(accept_offer(session, offer_id, actor_id))


@router.post("/offers/{offer_id}/decline", response_model=OfferRead)
def decline(offer_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> OfferRead:
    return OfferRead.from_record(decline_offer(session, offer_id, actor_id))


@router.post("/offers/{offer_id}/confirm-completion", response_model=OfferRead)
def helper_complete(offer_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> OfferRead:
    return OfferRead.from_record(confirm_helper(session, offer_id, actor_id))


@router.get("/system/health")
def health(session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise HTTPException(status_code=503, detail="Database unavailable") from error
    return {"status": "ok"}
