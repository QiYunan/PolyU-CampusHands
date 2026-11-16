"""HTTP endpoints; business rules live in services.py."""

from collections.abc import Iterator

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.campus_locations import location_options
from app.schemas import ClaimRequest, DemoRoleRead, HelperBoardRead, OfferRead, RequestCreate, RequestRead, RequestUpdate
from app.services import (
    InvalidDeadline, accept_offer, cancel_request, confirm_helper, confirm_requester,
    create_request, decline_offer, get_request_for_actor, helper_board,
    list_demo_roles, list_helper_offers, publish_request, claim_request,
    dismiss_request, restore_request, request_view, start_handoff,
    start_search, update_request, accept_proposal, decline_proposal,
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


@router.patch("/requests/{request_id}", response_model=RequestRead)
def patch_request(request_id: int, payload: RequestUpdate, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, update_request(session, request_id, payload, actor_id))


@router.post("/requests/{request_id}/search", response_model=RequestRead)
def search_request(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, start_search(session, request_id, actor_id))


@router.post("/requests/{request_id}/publish", response_model=RequestRead)
def publish(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    return request_view(session, publish_request(session, request_id, actor_id))


@router.get("/demo/roles", response_model=list[DemoRoleRead])
def demo_roles() -> list[DemoRoleRead]:
    return [DemoRoleRead.model_validate(role) for role in list_demo_roles()]


@router.get("/helper-board", response_model=HelperBoardRead)
def read_helper_board(session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> HelperBoardRead:
    return helper_board(session, actor_id)


@router.post("/requests/{request_id}/claim", response_model=OfferRead)
def claim(payload: ClaimRequest, request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> OfferRead:
    return OfferRead.from_record(claim_request(session, request_id, actor_id, payload))


@router.post("/offers/{offer_id}/accept-proposal", response_model=RequestRead)
def accept_substitute_proposal(offer_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    offer = accept_proposal(session, offer_id, actor_id)
    return request_view(session, offer.request)


@router.post("/offers/{offer_id}/decline-proposal", response_model=RequestRead)
def decline_substitute_proposal(offer_id: int, session: Session = Depends(get_session), actor_id: int = Depends(demo_actor)) -> RequestRead:
    offer = decline_proposal(session, offer_id, actor_id)
    return request_view(session, offer.request)


@router.post("/requests/{request_id}/dismiss", response_model=HelperBoardRead)
def dismiss(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> HelperBoardRead:
    dismiss_request(session, request_id, actor_id)
    return helper_board(session, actor_id)


@router.post("/requests/{request_id}/restore", response_model=HelperBoardRead)
def restore(request_id: int, session: Session = Depends(get_session), actor_id: int = Depends(helper_actor)) -> HelperBoardRead:
    restore_request(session, request_id, actor_id)
    return helper_board(session, actor_id)


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


@router.get("/locations")
def list_locations() -> list[dict[str, str]]:
    return location_options()
