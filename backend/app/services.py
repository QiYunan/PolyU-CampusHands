"""Deterministic, transactional BorrowLoop service operations."""

from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import ALICE_ID
from app.campus_locations import normalize_location
from app.matching import offered_item_matches
from app.models import AgentEvent, HelpOffer, HelpRequest, RequestDismissal, User
from app.privacy import public_text
from app.schemas import ClaimRequest, RequestCreate, RequestUpdate, SubstitutionPolicy
from app.state_machine import StateConflict, transition


class InvalidDeadline(ValueError):
    pass


class UnknownLocation(ValueError):
    pass


class NotFound(ValueError):
    pass


class Forbidden(ValueError):
    pass


class ClaimConflict(ValueError):
    """An already claimed request has a fixed, privacy-safe 409 response."""

    pass


# Published requests stay open until claimed, cancelled or past deadline.
ACTIVE_SEARCH = {"draft", "searching", "awaiting_response"}

ISSUE_MESSAGES = {
    "unknown_location": "交接地点尚未确认，请更正地点。",
    "no_item_inventory": "暂时无法提供这类物品。",
    "exact_preference_unavailable": "暂时无法满足指定的品牌或型号。",
    "alternatives_available_needs_confirmation": "有同类兼容选项，请先确认是否接受替代品。",
    "no_available_helper": "目前没有可联系的帮助者，请稍后重试。",
    "unreachable_before_deadline": "目前无法在截止时间前完成交接，请调整时间或地点。",
    "candidate_exhausted": "已尝试可联系的帮助者，请重新创建请求。",
}


def utc_naive(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must have a timezone")
    return now.astimezone(timezone.utc).replace(tzinfo=None)


@contextmanager
def write_transaction(session: Session):
    # A single SQLite writer owns selection and status changes until commit.
    session.execute(text("BEGIN IMMEDIATE"))
    try:
        yield
        session.commit()
    except BaseException:
        session.rollback()
        raise


def _require_request(session: Session, request_id: int) -> HelpRequest:
    request = session.get(HelpRequest, request_id)
    if request is None:
        raise NotFound("Request not found")
    return request


def _require_requester(request: HelpRequest, actor_id: int) -> None:
    if actor_id != request.requester_id:
        raise Forbidden("Only the requester can perform this action")


def _require_offer(session: Session, offer_id: int, actor_id: int) -> HelpOffer:
    offer = session.get(HelpOffer, offer_id)
    if offer is None:
        raise NotFound("Offer not found")
    if offer.helper_id != actor_id:
        raise Forbidden("This offer belongs to another helper")
    return offer


def _event(session: Session, request: HelpRequest, event_type: str, message: str, suffix: str = "request") -> None:
    # Only observable actions enter this table. No prompts or hidden model reasoning.
    session.add(AgentEvent(
        request_id=request.id,
        event_type=event_type,
        public_message=message,
        metadata_json="{}",
        dedupe_key=f"{request.id}:{event_type}:{suffix}",
    ))


def _set_issue(session: Session, request: HelpRequest, issue: str | None) -> None:
    if request.matching_issue == issue:
        return
    request.matching_issue = issue
    _event(session, request, "matching_issue_changed", ISSUE_MESSAGES[issue] if issue else "已重新检查匹配条件。", uuid4().hex)


def _pending_offer(session: Session, request: HelpRequest) -> HelpOffer | None:
    return session.scalar(select(HelpOffer).where(HelpOffer.request_id == request.id, HelpOffer.status == "pending"))


def _accepted_offer(session: Session, request: HelpRequest) -> HelpOffer | None:
    return session.scalar(select(HelpOffer).where(HelpOffer.request_id == request.id, HelpOffer.status == "accepted"))


def _proposed_offers(session: Session, request: HelpRequest) -> list[HelpOffer]:
    return list(session.scalars(select(HelpOffer).where(
        HelpOffer.request_id == request.id,
        HelpOffer.status == "proposed",
    ).order_by(HelpOffer.id)).all())


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _expire_request(session: Session, request: HelpRequest, now: datetime) -> None:
    for offer in session.scalars(select(HelpOffer).where(
        HelpOffer.request_id == request.id,
        HelpOffer.status.in_(("pending", "proposed")),
    )).all():
        offer.status = "expired"
        offer.responded_at = now
    transition(request, "expired")
    _event(session, request, "request_expired", "请求已到截止时间")


def create_request(session: Session, data: RequestCreate, actor_id: int = ALICE_ID) -> HelpRequest:
    if actor_id != ALICE_ID:
        raise Forbidden("Only Alice can create a request in Demo Mode")
    deadline_utc = data.deadline.astimezone(timezone.utc)
    if deadline_utc <= datetime.now(timezone.utc):
        raise InvalidDeadline("deadline must be in the future")
    if session.get(User, ALICE_ID) is None:
        raise RuntimeError("demo user Alice is unavailable")
    location = normalize_location(data.location)
    if location is None:
        raise UnknownLocation("请选择主校园内可识别的交接地点。")
    category = _enum_value(data.category)
    is_borrow = category == "borrow"
    policy = SubstitutionPolicy.equivalent_ok
    if is_borrow:
        policy = data.substitution_policy or (
            SubstitutionPolicy.ask_before_substitute
            if data.preferred_brand or data.preferred_model
            else SubstitutionPolicy.equivalent_ok
        )
    record = HelpRequest(
        requester_id=ALICE_ID,
        category=category,
        raw_text=public_text(data.raw_text) if data.raw_text else None,
        need_summary=public_text(data.need_summary),
        item_type=_enum_value(data.item_type) if data.item_type is not None else "other",
        preferred_brand=data.preferred_brand if is_borrow else None,
        preferred_model=data.preferred_model if is_borrow else None,
        substitution_policy=_enum_value(policy),
        location=location,
        deadline=deadline_utc.replace(tzinfo=None),
        urgency=_enum_value(data.urgency),
        status="draft",
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_request(session: Session, request_id: int) -> HelpRequest | None:
    return session.get(HelpRequest, request_id)


def get_request_for_actor(session: Session, request_id: int, actor_id: int) -> HelpRequest:
    request = _require_request(session, request_id)
    _require_requester(request, actor_id)
    return request


def list_demo_roles() -> list[dict[str, int | str]]:
    """Only the fixed fictional classroom identities are exposed."""
    from app.seed import DEMO_HELPERS

    return [{"id": ALICE_ID, "display_name": "Alice", "role": "requester"}] + [
        {"id": row[0], "display_name": row[1], "role": "helper"} for row in DEMO_HELPERS
    ]


def get_helper_for_actor(session: Session, actor_id: int) -> User:
    from app.seed import DEMO_HELPERS

    names = {row[0]: row[1] for row in DEMO_HELPERS}
    if actor_id not in names:
        raise Forbidden("Choose a Helper role in Demo Mode")
    helper = session.get(User, actor_id)
    if helper is None or helper.display_name != names[actor_id]:
        raise NotFound("Demo Helper is unavailable")
    return helper


def _was_published(session: Session, request_id: int) -> bool:
    return session.scalar(select(AgentEvent.id).where(
        AgentEvent.request_id == request_id,
        AgentEvent.event_type == "request_published",
    )) is not None


def helper_board(session: Session, actor_id: int, now: datetime | None = None):
    """Return every open request without inventory or location qualification."""
    from app.schemas import BoardEntryRead, BoardViewerRead, ClosedBoardRequestRead, HelperBoardRead, as_utc

    helper = get_helper_for_actor(session, actor_id)
    current = utc_naive(now)
    published = select(AgentEvent.id).where(
        AgentEvent.request_id == HelpRequest.id,
        AgentEvent.event_type == "request_published",
    ).exists()
    requests = session.scalars(select(HelpRequest).where(
        published, HelpRequest.status == "awaiting_response",
        HelpRequest.deadline > current,
    ).order_by(HelpRequest.id)).all()
    dismissed_ids = set(session.scalars(select(RequestDismissal.request_id).where(
        RequestDismissal.helper_id == actor_id,
    )).all())
    entries: list[tuple[tuple, BoardEntryRead]] = []
    hidden: list[tuple[tuple, BoardEntryRead]] = []
    urgency_order = {"high": 0, "normal": 1}
    for request in requests:
        row = BoardEntryRead(
            id=request.id, requester_name=request.requester.display_name,
            category=request.category, need_summary=request.need_summary,
            item_type=request.item_type,
            location=request.location, deadline=as_utc(request.deadline),
            urgency=request.urgency, status="awaiting_response",
        )
        order = (urgency_order.get(request.urgency, 2), request.deadline, request.created_at, request.id)
        (hidden if request.id in dismissed_ids else entries).append((order, row))
    closed = session.scalars(select(HelpRequest).where(
        published, HelpRequest.status.in_(("matched", "in_progress", "completed", "cancelled", "expired", "failed")),
    ).order_by(HelpRequest.id)).all()
    return HelperBoardRead(
        viewer=BoardViewerRead(id=helper.id, display_name=helper.display_name),
        requests=[row for _, row in sorted(entries, key=lambda pair: pair[0])],
        dismissed_requests=[row for _, row in sorted(hidden, key=lambda pair: pair[0])],
        closed_requests=[ClosedBoardRequestRead(id=request.id, status=request.status) for request in closed],
    )


def precheck_publication(session: Session, request_id: int, actor_id: int, now: datetime | None = None) -> str | None:
    """Read-only Agent precheck; Helpers decide their own ability to respond."""
    request = _require_request(session, request_id)
    _require_requester(request, actor_id)
    if request.status == "awaiting_response":
        return None
    if request.status not in {"draft", "searching"}:
        raise StateConflict("Only an unpublished request can be checked")
    current = utc_naive(now)
    if request.deadline <= current:
        return "unreachable_before_deadline"
    return None


def publish_request(session: Session, request_id: int, actor_id: int, now: datetime | None = None) -> HelpRequest:
    """Make a validated request visible to every Helper; create no Offer."""
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status == "awaiting_response":
            return request  # Repeated publish is idempotent.
        if request.status not in {"draft", "searching"}:
            raise StateConflict("Only an unpublished request can be published")
        if _pending_offer(session, request) is not None:
            raise StateConflict("A legacy Offer is still pending")
        if request.deadline <= current:
            _expire_request(session, request, current)
            return request
        _set_issue(session, request, None)
        transition(request, "awaiting_response")
        _event(session, request, "request_published", "请求已发布到校内求助广场")
        return request


def start_search(session: Session, request_id: int, actor_id: int, now: datetime | None = None) -> HelpRequest:
    """Compatibility alias: the old /search transport now publishes publicly."""
    return publish_request(session, request_id, actor_id, now)


def claim_request(
    session: Session,
    request_id: int,
    actor_id: int,
    response: ClaimRequest,
    now: datetime | None = None,
) -> HelpOffer:
    """Record a self-declared response; the first direct response wins atomically."""

    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        helper = get_helper_for_actor(session, actor_id)
        accepted = _accepted_offer(session, request)
        if accepted is not None:
            if accepted.helper_id == actor_id:
                return accepted
            raise ClaimConflict("该请求已被其他同学接下")
        if request.status != "awaiting_response" or not _was_published(session, request.id):
            raise StateConflict("该请求尚未开放或已关闭")
        if request.deadline <= current:
            raise StateConflict("该请求已过截止时间")
        if helper.id == request.requester_id:
            raise Forbidden("Requester cannot respond to their own request")
        if not response.capability_confirmed:
            raise StateConflict("请先确认能够在截止时间前完成该请求")

        existing = session.scalar(select(HelpOffer).where(
            HelpOffer.request_id == request.id,
            HelpOffer.helper_id == helper.id,
            HelpOffer.status.in_(("proposed", "accepted")),
        ))
        if existing is not None:
            return existing

        offered_brand = response.offered_brand if request.category == "borrow" else None
        offered_model = response.offered_model if request.category == "borrow" else None
        matches = request.category != "borrow" or offered_item_matches(request, offered_brand, offered_model)
        policy = request.substitution_policy or SubstitutionPolicy.equivalent_ok.value
        if policy not in {item.value for item in SubstitutionPolicy}:
            policy = SubstitutionPolicy.exact_only.value

        if request.category != "borrow" or matches:
            status = "accepted"
            response_type = "direct"
        elif policy == SubstitutionPolicy.exact_only.value:
            raise StateConflict("提供的品牌或型号不符合精确要求")
        elif policy == SubstitutionPolicy.ask_before_substitute.value:
            if not offered_brand and not offered_model:
                raise StateConflict("请填写拟提供替代品的品牌或型号")
            status = "proposed"
            response_type = "substitute"
        else:
            status = "accepted"
            response_type = "substitute"

        help_note = public_text(response.help_note) if response.help_note else None
        offer = HelpOffer(
            request_id=request.id,
            helper_id=helper.id,
            item_id=None,
            message=help_note,
            response_type=response_type,
            help_note=help_note,
            offered_brand=offered_brand,
            offered_model=offered_model,
            capability_confirmed_at=current,
            status=status,
            sent_at=current,
            responded_at=current if status == "accepted" else None,
            expires_at=request.deadline,
        )
        session.add(offer)
        session.flush()
        if status == "proposed":
            _event(session, request, "substitute_proposed", f"{helper.display_name} 提交了替代方案", str(offer.id))
            return offer

        for other in session.scalars(select(HelpOffer).where(
            HelpOffer.request_id == request.id,
            HelpOffer.id != offer.id,
            HelpOffer.status.in_(("pending", "proposed")),
        )).all():
            other.status = "cancelled"
            other.responded_at = current
        request.matching_issue = None
        transition(request, "matched")
        _event(session, request, "request_claimed", f"{helper.display_name} 已接受请求", str(offer.id))
        return offer


def dismiss_request(session: Session, request_id: int, actor_id: int) -> None:
    with write_transaction(session):
        request = _require_request(session, request_id)
        get_helper_for_actor(session, actor_id)
        if request.status != "awaiting_response" or not _was_published(session, request.id):
            raise StateConflict("该请求已关闭")
        existing = session.scalar(select(RequestDismissal).where(
            RequestDismissal.request_id == request_id,
            RequestDismissal.helper_id == actor_id,
        ))
        if existing is None:
            session.add(RequestDismissal(request_id=request_id, helper_id=actor_id))


def restore_request(session: Session, request_id: int, actor_id: int) -> None:
    with write_transaction(session):
        _require_request(session, request_id)
        get_helper_for_actor(session, actor_id)
        dismissal = session.scalar(select(RequestDismissal).where(
            RequestDismissal.request_id == request_id,
            RequestDismissal.helper_id == actor_id,
        ))
        if dismissal is not None:
            session.delete(dismissal)


def update_request(session: Session, request_id: int, edits: RequestUpdate, actor_id: int, now: datetime | None = None) -> HelpRequest:
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status not in {"draft", "searching"}:
            raise StateConflict("Request cannot be edited in this state")
        if _pending_offer(session, request) is not None:
            raise StateConflict("A helper is already considering this request")
        values = edits.model_dump(exclude_unset=True)
        if "location" in values:
            location = normalize_location(values["location"])
            if location is None:
                raise UnknownLocation("请选择主校园内可识别的交接地点。")
            request.location = location
        if "deadline" in values:
            deadline = utc_naive(values["deadline"])
            if deadline <= current or deadline < request.deadline:
                raise InvalidDeadline("deadline must be later than the current deadline and in the future")
            request.deadline = deadline
        _set_issue(session, request, None)
        return request


def _require_requester_proposal(session: Session, offer_id: int, actor_id: int) -> HelpOffer:
    offer = session.get(HelpOffer, offer_id)
    if offer is None:
        raise NotFound("Offer not found")
    _require_requester(offer.request, actor_id)
    return offer


def accept_proposal(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    """Atomically accept one substitute proposal if the request is still open."""

    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_requester_proposal(session, offer_id, actor_id)
        request = offer.request
        if offer.status == "accepted":
            return offer
        accepted = _accepted_offer(session, request)
        if accepted is not None:
            if accepted.id == offer.id:
                return accepted
            raise ClaimConflict("该请求已被其他同学接下")
        if offer.status != "proposed" or request.status != "awaiting_response" or not _was_published(session, request.id):
            raise StateConflict("该替代方案已失效")
        if request.deadline <= current:
            raise StateConflict("该请求已过截止时间")
        if offer.capability_confirmed_at is None:
            raise StateConflict("Helper capability confirmation is missing")

        offer.status = "accepted"
        offer.responded_at = current
        for other in session.scalars(select(HelpOffer).where(
            HelpOffer.request_id == request.id,
            HelpOffer.id != offer.id,
            HelpOffer.status.in_(("pending", "proposed")),
        )).all():
            other.status = "cancelled"
            other.responded_at = current
        request.matching_issue = None
        transition(request, "matched")
        _event(session, request, "request_claimed", f"{offer.helper.display_name} 的替代方案已被接受", str(offer.id))
        return offer


def decline_proposal(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_requester_proposal(session, offer_id, actor_id)
        if offer.status == "declined":
            return offer
        if offer.status != "proposed" or offer.request.status != "awaiting_response":
            raise StateConflict("该替代方案已失效")
        offer.status = "declined"
        offer.responded_at = current
        _event(session, offer.request, "substitute_declined", "求助者已拒绝替代方案", str(offer.id))
        return offer


def decline_offer(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    """Legacy inbox cleanup only; no serial replacement Offer is sent."""
    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_offer(session, offer_id, actor_id)
        if offer.status == "declined":
            return offer
        if offer.status != "pending" or offer.request.status != "awaiting_response":
            raise StateConflict("Offer cannot be declined")
        offer.status = "declined"
        offer.responded_at = current
        return offer


def accept_offer(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    """Retain idempotent reads of historical accepted Offers only."""
    _ = now
    with write_transaction(session):
        offer = _require_offer(session, offer_id, actor_id)
        if offer.status == "accepted":
            return offer
        raise StateConflict("请在求助广场认领请求")


def start_handoff(session: Session, request_id: int, actor_id: int) -> HelpRequest:
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        transition(request, "in_progress")
        _event(session, request, "handoff_started", "双方已开始交接")
        return request


def _finish_if_confirmed(session: Session, offer: HelpOffer) -> None:
    if offer.requester_confirmed_at is not None and offer.helper_confirmed_at is not None:
        transition(offer.request, "completed")
        _event(session, offer.request, "request_completed", "双方已确认，请求完成")


def confirm_requester(session: Session, request_id: int, actor_id: int, now: datetime | None = None) -> HelpRequest:
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status != "in_progress":
            raise StateConflict("Request is not in progress")
        offer = _accepted_offer(session, request)
        if offer is None:
            raise StateConflict("No accepted offer")
        if offer.requester_confirmed_at is None:
            offer.requester_confirmed_at = current
            _event(session, request, "requester_confirmed", "求助者已确认交接")
            _finish_if_confirmed(session, offer)
        return request


def confirm_helper(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_offer(session, offer_id, actor_id)
        if offer.status != "accepted" or offer.request.status != "in_progress":
            raise StateConflict("Handoff is not in progress")
        if offer.helper_confirmed_at is None:
            offer.helper_confirmed_at = current
            _event(session, offer.request, "helper_confirmed", f"{offer.helper.display_name} 已确认交接", str(offer.id))
            _finish_if_confirmed(session, offer)
        return offer


def cancel_request(session: Session, request_id: int, actor_id: int) -> HelpRequest:
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status not in {"draft", "searching", "awaiting_response", "matched", "in_progress"}:
            raise StateConflict("Request cannot be cancelled")
        offers = session.scalars(select(HelpOffer).where(
            HelpOffer.request_id == request.id,
            HelpOffer.status.in_(("pending", "proposed", "accepted")),
        )).all()
        for offer in offers:
            if offer.status == "accepted" and offer.item_id is not None and offer.item is not None:
                offer.item.available = True
            offer.status = "cancelled"
        transition(request, "cancelled")
        _event(session, request, "request_cancelled", "求助者已取消请求")
        return request


def advance_due(session: Session, now: datetime | None = None) -> None:
    current = utc_naive(now)
    with write_transaction(session):
        requests = session.scalars(select(HelpRequest).where(HelpRequest.status.in_(ACTIVE_SEARCH)).order_by(HelpRequest.id)).all()
        for request in requests:
            if request.deadline <= current:
                _expire_request(session, request, current)


def list_helper_offers(session: Session, helper_id: int, actor_id: int) -> list[HelpOffer]:
    if actor_id != helper_id:
        raise Forbidden("Another helper's inbox is private")
    get_helper_for_actor(session, actor_id)
    return session.scalars(select(HelpOffer).where(HelpOffer.helper_id == helper_id).order_by(HelpOffer.id.desc())).all()


def request_view(session: Session, request: HelpRequest):
    from app.schemas import EventRead, ProposalRead, RequestRead

    timeline_events = {
        "request_parsed", "request_published", "request_claimed",
        "handoff_started", "request_completed", "request_cancelled", "request_expired",
    }
    events = session.scalars(select(AgentEvent).where(
        AgentEvent.request_id == request.id,
        AgentEvent.event_type.in_(timeline_events),
    ).order_by(AgentEvent.id)).all()
    accepted = _accepted_offer(session, request)
    proposals = _proposed_offers(session, request)
    return RequestRead.from_record(
        request,
        events=[EventRead.from_record(event) for event in events],
        matched_helper=accepted.helper.display_name if accepted else None,
        handoff_location=request.location if accepted else None,
        requester_confirmed=bool(accepted and accepted.requester_confirmed_at),
        helper_confirmed=bool(accepted and accepted.helper_confirmed_at),
        proposals=[ProposalRead(
            id=offer.id,
            helper_name=offer.helper.display_name,
            help_note=offer.help_note,
            offered_brand=offer.offered_brand,
            offered_model=offer.offered_model,
            status=offer.status,
        ) for offer in proposals],
        helper_note=accepted.help_note if accepted else None,
        offered_brand=accepted.offered_brand if accepted else None,
        offered_model=accepted.offered_model if accepted else None,
        response_type=accepted.response_type if accepted else None,
    )
