"""Trusted service-layer operations for M07 Helper supply and invitations."""

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.campus_locations import normalize_location
from app.matching import offered_item_matches
from app.models import (
    AgentEvent,
    DailyAvailability,
    DailyAvailableItem,
    DailyAvailableService,
    HelpInvitation,
    HelpOffer,
    HelpRequest,
    InvitationBatch,
    UserItem,
    UserServiceCapability,
)
from app.privacy import public_text
from app.schemas import as_utc
from app.services import (
    ClaimConflict,
    Forbidden,
    NotFound,
    _event,
    get_helper_for_actor,
    utc_naive,
    write_transaction,
)
from app.state_machine import StateConflict, transition
from app.supply_matching import (
    HONG_KONG,
    SupplyCandidate,
    candidate_for_helper,
    reliability_level,
    search_supply_candidates,
)
from app.supply_schemas import (
    DailyAvailabilityData,
    DailyAvailabilityInput,
    DailyAvailabilityRead,
    HelperCandidateRead,
    HelperProfileRead,
    HelperProfileUpdate,
    HelperSearchRead,
    InvitationBatchRead,
    InvitationInboxRead,
    InvitationRead,
    ProfileItemRead,
    ProfileServiceRead,
    RequestInvitationsRead,
    SubstituteProposal,
)


class CandidatesStale(StateConflict):
    pass


def _require_request(session: Session, request_id: int) -> HelpRequest:
    request = session.get(HelpRequest, request_id)
    if request is None:
        raise NotFound("Request not found")
    return request


def _require_requester(request: HelpRequest, actor_id: int) -> None:
    if request.requester_id != actor_id:
        raise Forbidden("Only the requester may perform this action")


def _current_hk_date(now: datetime | None = None):
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(HONG_KONG).date()


def _as_hkt(value: datetime) -> datetime:
    return as_utc(value).astimezone(HONG_KONG)


def _profile_view(session: Session, user_id: int) -> HelperProfileRead:
    items = session.scalars(select(UserItem).where(UserItem.user_id == user_id).order_by(UserItem.id)).all()
    services = session.scalars(select(UserServiceCapability).where(
        UserServiceCapability.user_id == user_id,
    ).order_by(UserServiceCapability.id)).all()
    return HelperProfileRead(
        user_id=user_id,
        items=[ProfileItemRead(
            id=item.id, item_type=item.item_type, item_name=item.item_name,
            brand=item.brand, model=item.model, active=item.is_active,
        ) for item in items],
        services=[ProfileServiceRead(
            id=service.id, service_code=service.service_code,
            service_name=service.service_name, active=service.active,
        ) for service in services],
    )


def get_helper_profile(session: Session, user_id: int, actor_id: int) -> HelperProfileRead:
    if user_id != actor_id:
        raise Forbidden("Another Helper's profile is private")
    get_helper_for_actor(session, actor_id)
    return _profile_view(session, user_id)


def update_helper_profile(
    session: Session,
    user_id: int,
    actor_id: int,
    payload: HelperProfileUpdate,
) -> HelperProfileRead:
    if user_id != actor_id:
        raise Forbidden("Another Helper's profile is private")
    with write_transaction(session):
        get_helper_for_actor(session, actor_id)
        existing_items = {item.id: item for item in session.scalars(
            select(UserItem).where(UserItem.user_id == user_id)
        ).all()}
        existing_services = {service.id: service for service in session.scalars(
            select(UserServiceCapability).where(UserServiceCapability.user_id == user_id)
        ).all()}
        item_keys: set[tuple[str, str]] = set()
        service_keys: set[tuple[str, str]] = set()
        kept_items: set[int] = set()
        kept_services: set[int] = set()

        for value in payload.items:
            key = (value.item_type.value, value.item_name.casefold())
            if key in item_keys:
                raise StateConflict("长期物品不能重复")
            item_keys.add(key)
            if value.id is None:
                item = UserItem(user_id=user_id, item_type=value.item_type.value, item_name=value.item_name)
                session.add(item)
                session.flush()
                existing_items[item.id] = item
            else:
                item = existing_items.get(value.id)
                if item is None:
                    raise Forbidden("Item does not belong to this Helper")
            item.item_type = value.item_type.value
            item.item_name = value.item_name
            item.brand = value.brand
            item.model = value.model
            item.is_active = value.active
            kept_items.add(item.id)

        for value in payload.services:
            key = (value.service_code.value, value.service_name.casefold())
            if key in service_keys:
                raise StateConflict("长期服务不能重复")
            service_keys.add(key)
            if value.id is None:
                service = UserServiceCapability(
                    user_id=user_id,
                    service_code=value.service_code.value,
                    service_name=value.service_name,
                )
                session.add(service)
                session.flush()
                existing_services[service.id] = service
            else:
                service = existing_services.get(value.id)
                if service is None:
                    raise Forbidden("Service does not belong to this Helper")
            service.service_code = value.service_code.value
            service.service_name = value.service_name
            service.active = value.active
            kept_services.add(service.id)

        for item_id, item in existing_items.items():
            if item_id not in kept_items:
                item.is_active = False
        for service_id, service in existing_services.items():
            if service_id not in kept_services:
                service.active = False
    return _profile_view(session, user_id)


def _daily_ids(session: Session, daily_id: int) -> tuple[list[int], list[int]]:
    item_ids = list(session.scalars(select(DailyAvailableItem.item_id).where(
        DailyAvailableItem.daily_availability_id == daily_id,
    ).order_by(DailyAvailableItem.item_id)).all())
    service_ids = list(session.scalars(select(DailyAvailableService.service_id).where(
        DailyAvailableService.daily_availability_id == daily_id,
    ).order_by(DailyAvailableService.service_id)).all())
    return item_ids, service_ids


def get_daily_availability(
    session: Session,
    user_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> DailyAvailabilityRead:
    if user_id != actor_id:
        raise Forbidden("Another Helper's daily status is private")
    get_helper_for_actor(session, actor_id)
    local_date = _current_hk_date(now)
    current = session.scalar(select(DailyAvailability).where(
        DailyAvailability.user_id == user_id,
        DailyAvailability.local_date == local_date,
    ))
    previous = session.scalar(select(DailyAvailability).where(
        DailyAvailability.user_id == user_id,
        DailyAvailability.local_date < local_date,
    ).order_by(DailyAvailability.local_date.desc(), DailyAvailability.id.desc()))
    suggested_items, suggested_services = _daily_ids(session, previous.id) if previous else ([], [])
    availability = None
    if current is not None:
        item_ids, service_ids = _daily_ids(session, current.id)
        availability = DailyAvailabilityData(
            willing=current.willing,
            available_from=_as_hkt(current.available_from),
            available_until=_as_hkt(current.available_until),
            campus_building=current.campus_building,
            accepts_urgent=current.accepts_urgent,
            item_ids=item_ids,
            service_ids=service_ids,
        )
    return DailyAvailabilityRead(
        local_date=local_date,
        availability=availability,
        suggested_item_ids=suggested_items,
        suggested_service_ids=suggested_services,
    )


def update_daily_availability(
    session: Session,
    user_id: int,
    actor_id: int,
    payload: DailyAvailabilityInput,
    now: datetime | None = None,
) -> DailyAvailabilityRead:
    if user_id != actor_id:
        raise Forbidden("Another Helper's daily status is private")
    local_date = _current_hk_date(now)
    start_hk = payload.available_from.astimezone(HONG_KONG)
    end_hk = payload.available_until.astimezone(HONG_KONG)
    if start_hk.date() != local_date or end_hk.date() != local_date:
        raise StateConflict("今日状态的起止时间必须属于香港本地的今天")
    building = normalize_location(payload.campus_building)
    if building is None:
        raise StateConflict("请选择主校园内可识别的楼栋")

    with write_transaction(session):
        get_helper_for_actor(session, actor_id)
        items = session.scalars(select(UserItem).where(UserItem.id.in_(payload.item_ids))).all() if payload.item_ids else []
        services = session.scalars(select(UserServiceCapability).where(
            UserServiceCapability.id.in_(payload.service_ids)
        )).all() if payload.service_ids else []
        if len(items) != len(payload.item_ids) or any(item.user_id != user_id or not item.is_active for item in items):
            raise Forbidden("Today item selection contains an unavailable item")
        if len(services) != len(payload.service_ids) or any(
            service.user_id != user_id or not service.active for service in services
        ):
            raise Forbidden("Today service selection contains an unavailable service")
        daily = session.scalar(select(DailyAvailability).where(
            DailyAvailability.user_id == user_id,
            DailyAvailability.local_date == local_date,
        ))
        if daily is None:
            daily = DailyAvailability(
                user_id=user_id,
                local_date=local_date,
                willing=payload.willing,
                available_from=utc_naive(payload.available_from),
                available_until=utc_naive(payload.available_until),
                campus_building=building,
                accepts_urgent=payload.accepts_urgent,
            )
            session.add(daily)
            session.flush()
        daily.willing = payload.willing
        daily.available_from = utc_naive(payload.available_from)
        daily.available_until = utc_naive(payload.available_until)
        daily.campus_building = building
        daily.accepts_urgent = payload.accepts_urgent
        session.execute(delete(DailyAvailableItem).where(DailyAvailableItem.daily_availability_id == daily.id))
        session.execute(delete(DailyAvailableService).where(DailyAvailableService.daily_availability_id == daily.id))
        session.add_all(DailyAvailableItem(daily_availability_id=daily.id, item_id=item.id) for item in items)
        session.add_all(DailyAvailableService(daily_availability_id=daily.id, service_id=service.id) for service in services)
    return get_daily_availability(session, user_id, actor_id, now)


def search_helpers(
    session: Session,
    request_id: int,
    actor_id: int,
    limit: int,
    now: datetime | None = None,
) -> HelperSearchRead:
    current = utc_naive(now)
    request = _require_request(session, request_id)
    _require_requester(request, actor_id)
    if request.status not in {"draft", "searching"}:
        raise StateConflict("Request is not available for a new Helper search")
    if request.deadline <= current:
        raise StateConflict("Request deadline has passed")
    result = search_supply_candidates(session, request, current)
    return HelperSearchRead(
        request_id=request.id,
        searched_at=as_utc(current),
        candidates=[HelperCandidateRead(
            helper_id=candidate.helper.id,
            display_name=candidate.helper.display_name,
            match_reason=candidate.match_reason,
            estimated_arrival_minutes=candidate.estimated_arrival_minutes,
            available_from=as_utc(candidate.availability.available_from),
            available_until=as_utc(candidate.availability.available_until),
            reliability_level=reliability_level(candidate.helper.reliability_score),
            is_substitute=candidate.is_substitute,
        ) for candidate in result.candidates[:limit]],
        issue=result.issue,
    )


def create_invitations(
    session: Session,
    request_id: int,
    actor_id: int,
    helper_ids: list[int],
    now: datetime | None = None,
) -> RequestInvitationsRead:
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status not in {"draft", "searching"} or request.deadline <= current:
            raise StateConflict("Request is not available for invitations")
        open_batch = session.scalar(select(InvitationBatch).where(
            InvitationBatch.request_id == request.id,
            InvitationBatch.status == "open",
        ))
        if open_batch is not None:
            raise StateConflict("Close the current invitation round first")
        result = search_supply_candidates(session, request, current)
        candidates = {candidate.helper.id: candidate for candidate in result.candidates}
        if any(helper_id not in candidates for helper_id in helper_ids):
            raise CandidatesStale("候选状态已变化，请重新搜索。")
        round_number = (session.scalar(select(func.max(InvitationBatch.round_number)).where(
            InvitationBatch.request_id == request.id,
        )) or 0) + 1
        batch = InvitationBatch(request_id=request.id, round_number=round_number, status="open", created_at=current)
        session.add(batch)
        session.flush()
        for helper_id in helper_ids:
            candidate = candidates[helper_id]
            session.add(HelpInvitation(
                batch_id=batch.id,
                request_id=request.id,
                helper_id=helper_id,
                candidate_item_id=candidate.item.id if candidate.item else None,
                candidate_service_id=candidate.service.id if candidate.service else None,
                match_reason=candidate.match_reason,
                response_type="substitute" if candidate.is_substitute else "direct",
                status="pending",
                sent_at=current,
                expires_at=request.deadline,
            ))
        transition(request, "awaiting_response")
        _event(session, request, "invitations_sent", "已向选定的 Helper 发送邀请", str(batch.id))
    return request_invitations(session, request_id, actor_id)


def _offer_for_invitation(session: Session, invitation_id: int) -> HelpOffer | None:
    return session.scalar(select(HelpOffer).where(HelpOffer.invitation_id == invitation_id))


def _invitation_view(session: Session, invitation: HelpInvitation) -> InvitationRead:
    offer = _offer_for_invitation(session, invitation.id)
    item = invitation.proposed_item or invitation.candidate_item
    service = invitation.candidate_service
    return InvitationRead(
        id=invitation.id,
        batch_id=invitation.batch_id,
        round_number=invitation.batch.round_number,
        request_id=invitation.request_id,
        helper_id=invitation.helper_id,
        helper_name=invitation.helper.display_name,
        requester_name=invitation.request.requester.display_name,
        category=invitation.request.category,
        need_summary=invitation.request.need_summary,
        location=invitation.request.location,
        deadline=as_utc(invitation.request.deadline),
        urgency=invitation.request.urgency or "normal",
        match_reason=invitation.match_reason,
        response_type=invitation.response_type,
        status=invitation.status,
        decline_reason=invitation.decline_reason,
        note=invitation.note,
        item_id=item.id if item else None,
        item_name=item.item_name if item else None,
        service_id=service.id if service else None,
        service_name=service.service_name if service else None,
        request_status=invitation.request.status,
        sent_at=as_utc(invitation.sent_at),
        responded_at=as_utc(invitation.responded_at) if invitation.responded_at else None,
        expires_at=as_utc(invitation.expires_at),
        offer_id=offer.id if offer else None,
        helper_confirmed=bool(offer and offer.helper_confirmed_at),
    )


def request_invitations(session: Session, request_id: int, actor_id: int) -> RequestInvitationsRead:
    request = _require_request(session, request_id)
    _require_requester(request, actor_id)
    batches = session.scalars(select(InvitationBatch).where(
        InvitationBatch.request_id == request_id,
    ).order_by(InvitationBatch.round_number)).all()
    return RequestInvitationsRead(
        request_id=request.id,
        request_status=request.status,
        batches=[InvitationBatchRead(
            id=batch.id,
            round_number=batch.round_number,
            status=batch.status,
            created_at=as_utc(batch.created_at),
            closed_at=as_utc(batch.closed_at) if batch.closed_at else None,
            invitations=[_invitation_view(session, invitation) for invitation in session.scalars(
                select(HelpInvitation).where(HelpInvitation.batch_id == batch.id).order_by(HelpInvitation.id)
            ).all()],
        ) for batch in batches],
    )


def helper_invitations(session: Session, helper_id: int, actor_id: int) -> InvitationInboxRead:
    if helper_id != actor_id:
        raise Forbidden("Another Helper's invitations are private")
    get_helper_for_actor(session, actor_id)
    invitations = session.scalars(select(HelpInvitation).where(
        HelpInvitation.helper_id == helper_id,
    ).order_by(HelpInvitation.id.desc())).all()
    pending: list[InvitationRead] = []
    active: list[InvitationRead] = []
    history: list[InvitationRead] = []
    for invitation in invitations:
        view = _invitation_view(session, invitation)
        if invitation.status in {"pending", "proposed"} and invitation.request.status == "awaiting_response":
            pending.append(view)
        elif invitation.status == "accepted" and invitation.request.status in {"matched", "in_progress"}:
            active.append(view)
        else:
            history.append(view)
    return InvitationInboxRead(helper_id=helper_id, pending=pending, active=active, history=history)


def _require_invitation(session: Session, invitation_id: int) -> HelpInvitation:
    invitation = session.get(HelpInvitation, invitation_id)
    if invitation is None:
        raise NotFound("Invitation not found")
    return invitation


def invitation_for_actor(session: Session, invitation_id: int, actor_id: int) -> InvitationRead:
    invitation = _require_invitation(session, invitation_id)
    if actor_id not in {invitation.helper_id, invitation.request.requester_id}:
        raise Forbidden("Invitation is private")
    return _invitation_view(session, invitation)


def _capability_is_valid(
    session: Session,
    invitation: HelpInvitation,
    current: datetime,
    item: UserItem | None = None,
) -> bool:
    candidate = candidate_for_helper(session, invitation.request, invitation.helper_id, current)
    if candidate is None:
        return False
    if invitation.request.category == "service":
        return candidate.service is not None and candidate.service.id == invitation.candidate_service_id
    target = item or invitation.candidate_item
    if target is None or target.user_id != invitation.helper_id or target.item_type != invitation.request.item_type:
        return False
    if not target.is_active or not target.available:
        return False
    daily = candidate.availability
    selected = session.scalar(select(DailyAvailableItem.id).where(
        DailyAvailableItem.daily_availability_id == daily.id,
        DailyAvailableItem.item_id == target.id,
    ))
    occupied = session.scalar(select(HelpOffer.id).join(
        HelpRequest, HelpRequest.id == HelpOffer.request_id,
    ).where(
        HelpOffer.item_id == target.id,
        HelpOffer.status == "accepted",
        HelpRequest.status.in_(("matched", "in_progress")),
    ))
    return selected is not None and occupied is None


def _accept_locked(
    session: Session,
    invitation: HelpInvitation,
    current: datetime,
    item: UserItem | None = None,
) -> HelpOffer:
    existing = _offer_for_invitation(session, invitation.id)
    if existing is not None and existing.status == "accepted":
        return existing
    accepted = session.scalar(select(HelpOffer).where(
        HelpOffer.request_id == invitation.request_id,
        HelpOffer.status == "accepted",
    ))
    if accepted is not None:
        raise ClaimConflict("Request already matched")
    if invitation.status not in {"pending", "proposed"} or invitation.batch.status != "open":
        raise StateConflict("Invitation is no longer active")
    if invitation.request.status != "awaiting_response" or invitation.request.deadline <= current:
        raise StateConflict("Request is no longer accepting invitations")
    target_item = item or invitation.proposed_item or invitation.candidate_item
    if not _capability_is_valid(session, invitation, current, target_item):
        raise CandidatesStale("候选状态已变化，请重新搜索。")

    offer = HelpOffer(
        request_id=invitation.request_id,
        helper_id=invitation.helper_id,
        invitation_id=invitation.id,
        item_id=target_item.id if target_item else None,
        service_capability_id=invitation.candidate_service_id,
        message=invitation.note,
        response_type=invitation.response_type,
        help_note=invitation.note,
        offered_brand=target_item.brand if target_item else None,
        offered_model=target_item.model if target_item else None,
        capability_confirmed_at=current,
        status="accepted",
        sent_at=invitation.sent_at,
        responded_at=current,
        expires_at=invitation.request.deadline,
    )
    session.add(offer)
    if target_item is not None:
        target_item.available = False
    invitation.status = "accepted"
    invitation.responded_at = current
    invitation.batch.status = "matched"
    invitation.batch.closed_at = current
    for other in session.scalars(select(HelpInvitation).where(
        HelpInvitation.batch_id == invitation.batch_id,
        HelpInvitation.id != invitation.id,
        HelpInvitation.status.in_(("pending", "proposed")),
    )).all():
        other.status = "cancelled"
        other.responded_at = current
    transition(invitation.request, "matched")
    _event(
        session,
        invitation.request,
        "request_claimed",
        f"{invitation.helper.display_name} 已接受邀请",
        f"invite:{invitation.id}",
    )
    session.flush()
    return offer


def accept_invitation(
    session: Session,
    invitation_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        invitation = _require_invitation(session, invitation_id)
        if invitation.helper_id != actor_id:
            raise Forbidden("Invitation belongs to another Helper")
        get_helper_for_actor(session, actor_id)
        return _accept_locked(session, invitation, current)


def decline_invitation(
    session: Session,
    invitation_id: int,
    actor_id: int,
    reason: str,
    now: datetime | None = None,
) -> HelpInvitation:
    current = utc_naive(now)
    with write_transaction(session):
        invitation = _require_invitation(session, invitation_id)
        if invitation.helper_id != actor_id:
            raise Forbidden("Invitation belongs to another Helper")
        if invitation.status == "declined" and invitation.decline_reason == reason:
            return invitation
        if invitation.status not in {"pending", "proposed"} or invitation.batch.status != "open":
            raise StateConflict("Invitation is no longer active")
        invitation.status = "declined"
        invitation.decline_reason = reason
        invitation.responded_at = current
        _event(session, invitation.request, "invitation_declined", "一名 Helper 已更新邀请状态", f"invite:{invitation.id}")
        return invitation


def propose_substitute(
    session: Session,
    invitation_id: int,
    actor_id: int,
    payload: SubstituteProposal,
    now: datetime | None = None,
) -> HelpInvitation:
    current = utc_naive(now)
    with write_transaction(session):
        invitation = _require_invitation(session, invitation_id)
        if invitation.helper_id != actor_id:
            raise Forbidden("Invitation belongs to another Helper")
        if invitation.request.category != "borrow" or invitation.status != "pending":
            raise StateConflict("This invitation cannot receive a substitute")
        item = session.get(UserItem, payload.item_id)
        if item is None or not _capability_is_valid(session, invitation, current, item):
            raise CandidatesStale("候选状态已变化，请重新搜索。")
        if invitation.request.substitution_policy == "exact_only" and not offered_item_matches(
            invitation.request, item.brand, item.model,
        ):
            raise StateConflict("The request accepts only the exact preference")
        invitation.proposed_item_id = item.id
        invitation.note = public_text(payload.note) if payload.note else None
        invitation.response_type = "substitute"
        if offered_item_matches(invitation.request, item.brand, item.model) or invitation.request.substitution_policy == "equivalent_ok":
            invitation.candidate_item_id = item.id
            invitation.match_reason = "compatible"
            _accept_locked(session, invitation, current, item)
        else:
            invitation.status = "proposed"
            invitation.responded_at = current
            _event(session, invitation.request, "substitute_proposed", f"{invitation.helper.display_name} 提交了替代方案", f"invite:{invitation.id}")
        return invitation


def accept_invitation_substitute(
    session: Session,
    invitation_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        invitation = _require_invitation(session, invitation_id)
        _require_requester(invitation.request, actor_id)
        if invitation.status != "proposed" or invitation.proposed_item is None:
            raise StateConflict("Substitute proposal is no longer active")
        invitation.candidate_item_id = invitation.proposed_item_id
        invitation.match_reason = "compatible"
        invitation.response_type = "substitute"
        return _accept_locked(session, invitation, current, invitation.proposed_item)


def decline_invitation_substitute(
    session: Session,
    invitation_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> HelpInvitation:
    current = utc_naive(now)
    with write_transaction(session):
        invitation = _require_invitation(session, invitation_id)
        _require_requester(invitation.request, actor_id)
        if invitation.status != "proposed":
            raise StateConflict("Substitute proposal is no longer active")
        invitation.status = "declined"
        invitation.decline_reason = "substitute_declined"
        invitation.responded_at = current
        _event(session, invitation.request, "substitute_declined", "求助者已拒绝替代方案", f"invite:{invitation.id}")
        return invitation


def close_invitation_round(
    session: Session,
    request_id: int,
    actor_id: int,
    now: datetime | None = None,
) -> RequestInvitationsRead:
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        batch = session.scalar(select(InvitationBatch).where(
            InvitationBatch.request_id == request_id,
            InvitationBatch.status == "open",
        ))
        if batch is None:
            raise StateConflict("No open invitation round")
        if request.status != "awaiting_response":
            raise StateConflict("Request is no longer awaiting invitations")
        for invitation in session.scalars(select(HelpInvitation).where(
            HelpInvitation.batch_id == batch.id,
            HelpInvitation.status.in_(("pending", "proposed")),
        )).all():
            invitation.status = "cancelled"
            invitation.responded_at = current
        batch.status = "closed"
        batch.closed_at = current
        transition(request, "searching")
        _event(session, request, "invitation_round_closed", "求助者已结束本轮邀请", str(batch.id))
    return request_invitations(session, request_id, actor_id)


def advance_supply_due(session: Session, now: datetime | None = None) -> None:
    current = utc_naive(now)
    with write_transaction(session):
        batches = session.scalars(select(InvitationBatch).join(
            HelpRequest, HelpRequest.id == InvitationBatch.request_id,
        ).where(
            InvitationBatch.status == "open",
            HelpRequest.deadline <= current,
        )).all()
        for batch in batches:
            batch.status = "expired"
            batch.closed_at = current
            for invitation in session.scalars(select(HelpInvitation).where(
                HelpInvitation.batch_id == batch.id,
                HelpInvitation.status.in_(("pending", "proposed")),
            )).all():
                invitation.status = "expired"
                invitation.responded_at = current
