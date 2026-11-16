"""M07 HTTP transport; all supply and invitation rules live in services."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.routes import demo_actor, get_session, helper_actor
from app.schemas import OfferRead
from app.supply_schemas import (
    DailyAvailabilityInput,
    DailyAvailabilityRead,
    HelperProfileRead,
    HelperProfileUpdate,
    HelperSearchInput,
    HelperSearchRead,
    InvitationCreate,
    InvitationDecline,
    InvitationInboxRead,
    InvitationRead,
    RequestInvitationsRead,
    SubstituteProposal,
)
from app.supply_services import (
    accept_invitation,
    accept_invitation_substitute,
    close_invitation_round,
    create_invitations,
    decline_invitation,
    decline_invitation_substitute,
    get_daily_availability,
    get_helper_profile,
    helper_invitations,
    invitation_for_actor,
    propose_substitute,
    request_invitations,
    search_helpers,
    update_daily_availability,
    update_helper_profile,
)


router = APIRouter(prefix="/api")


@router.get("/demo/users/{user_id}/helper-profile", response_model=HelperProfileRead)
def read_helper_profile(
    user_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> HelperProfileRead:
    return get_helper_profile(session, user_id, actor_id)


@router.put("/demo/users/{user_id}/helper-profile", response_model=HelperProfileRead)
def put_helper_profile(
    user_id: int,
    payload: HelperProfileUpdate,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> HelperProfileRead:
    return update_helper_profile(session, user_id, actor_id, payload)


@router.get("/demo/users/{user_id}/daily-availability", response_model=DailyAvailabilityRead)
def read_daily_availability(
    user_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> DailyAvailabilityRead:
    return get_daily_availability(session, user_id, actor_id)


@router.put("/demo/users/{user_id}/daily-availability", response_model=DailyAvailabilityRead)
def put_daily_availability(
    user_id: int,
    payload: DailyAvailabilityInput,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> DailyAvailabilityRead:
    return update_daily_availability(session, user_id, actor_id, payload)


@router.post("/helpers/search", response_model=HelperSearchRead)
def post_helper_search(
    payload: HelperSearchInput,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> HelperSearchRead:
    return search_helpers(session, payload.request_id, actor_id, payload.limit)


@router.post("/requests/{request_id}/invitations", response_model=RequestInvitationsRead)
def post_invitations(
    request_id: int,
    payload: InvitationCreate,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> RequestInvitationsRead:
    return create_invitations(session, request_id, actor_id, payload.helper_ids)


@router.get("/requests/{request_id}/invitations", response_model=RequestInvitationsRead)
def get_request_invitations(
    request_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> RequestInvitationsRead:
    return request_invitations(session, request_id, actor_id)


@router.post("/requests/{request_id}/invitations/close", response_model=RequestInvitationsRead)
def close_request_invitations(
    request_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> RequestInvitationsRead:
    return close_invitation_round(session, request_id, actor_id)


@router.get("/helpers/{helper_id}/invitations", response_model=InvitationInboxRead)
def get_helper_invitations(
    helper_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> InvitationInboxRead:
    return helper_invitations(session, helper_id, actor_id)


@router.post("/invitations/{invitation_id}/accept", response_model=OfferRead)
def accept_helper_invitation(
    invitation_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> OfferRead:
    return OfferRead.from_record(accept_invitation(session, invitation_id, actor_id))


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationRead)
def decline_helper_invitation(
    invitation_id: int,
    payload: InvitationDecline,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> InvitationRead:
    decline_invitation(session, invitation_id, actor_id, payload.reason)
    return invitation_for_actor(session, invitation_id, actor_id)


@router.post("/invitations/{invitation_id}/propose-substitute", response_model=InvitationRead)
def propose_invitation_substitute(
    invitation_id: int,
    payload: SubstituteProposal,
    session: Session = Depends(get_session),
    actor_id: int = Depends(helper_actor),
) -> InvitationRead:
    propose_substitute(session, invitation_id, actor_id, payload)
    return invitation_for_actor(session, invitation_id, actor_id)


@router.post("/invitations/{invitation_id}/accept-substitute", response_model=OfferRead)
def accept_requester_substitute(
    invitation_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> OfferRead:
    return OfferRead.from_record(accept_invitation_substitute(session, invitation_id, actor_id))


@router.post("/invitations/{invitation_id}/decline-substitute", response_model=InvitationRead)
def decline_requester_substitute(
    invitation_id: int,
    session: Session = Depends(get_session),
    actor_id: int = Depends(demo_actor),
) -> InvitationRead:
    decline_invitation_substitute(session, invitation_id, actor_id)
    return invitation_for_actor(session, invitation_id, actor_id)
