"""Deterministic, transactional BorrowLoop service operations."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.database import ALICE_ID
from app.matching import rank_candidates
from app.models import AgentEvent, HelpOffer, HelpRequest, User, UserItem
from app.privacy import public_text
from app.schemas import RequestCreate
from app.state_machine import StateConflict, transition


class InvalidDeadline(ValueError):
    pass


class NotFound(ValueError):
    pass


class Forbidden(ValueError):
    pass


# Drafts stay untouched until the requester explicitly starts matching.
ACTIVE_SEARCH = {"searching", "awaiting_response"}
OFFER_TIMEOUT_SECONDS = 30


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


def _pending_offer(session: Session, request: HelpRequest) -> HelpOffer | None:
    return session.scalar(select(HelpOffer).where(HelpOffer.request_id == request.id, HelpOffer.status == "pending"))


def _accepted_offer(session: Session, request: HelpRequest) -> HelpOffer | None:
    return session.scalar(select(HelpOffer).where(HelpOffer.request_id == request.id, HelpOffer.status == "accepted"))


def _expire_request(session: Session, request: HelpRequest, now: datetime) -> None:
    pending = _pending_offer(session, request)
    if pending is not None:
        pending.status = "expired"
        pending.responded_at = now
        _event(session, request, "offer_expired", f"{pending.helper.display_name} 的邀请已超时", str(pending.id))
    transition(request, "expired")
    _event(session, request, "request_expired", "请求已到截止时间")


def _dispatch_next(session: Session, request: HelpRequest, now: datetime, offer_message: str | None = None) -> None:
    if request.deadline <= now:
        _expire_request(session, request, now)
        return
    candidates = rank_candidates(session, request, now)
    if not candidates:
        transition(request, "failed")
        _event(session, request, "search_failed", "未找到符合条件的帮助者")
        return
    helper, item = candidates[0]
    offer = HelpOffer(
        request_id=request.id,
        helper_id=helper.id,
        item_id=item.id,
        status="pending",
        sent_at=now,
        expires_at=min(request.deadline, now + timedelta(seconds=OFFER_TIMEOUT_SECONDS)),
        message=offer_message or f"有同学想在 {request.location} 借用 {request.item_type}，请在邀请有效期内回复。",
    )
    session.add(offer)
    session.flush()
    transition(request, "awaiting_response")
    _event(session, request, "offer_sent", f"已联系 {helper.display_name}", str(offer.id))


def _expire_offer_and_continue(session: Session, offer: HelpOffer, now: datetime) -> None:
    if offer.status != "pending":
        return
    request = offer.request
    offer.status = "expired"
    offer.responded_at = now
    _event(session, request, "offer_expired", f"{offer.helper.display_name} 的邀请已超时", str(offer.id))
    if request.deadline <= now:
        transition(request, "expired")
        _event(session, request, "request_expired", "请求已到截止时间")
    else:
        transition(request, "searching")
        _dispatch_next(session, request, now)


def create_request(session: Session, data: RequestCreate, actor_id: int = ALICE_ID) -> HelpRequest:
    if actor_id != ALICE_ID:
        raise Forbidden("Only Alice can create a request in Demo Mode")
    deadline_utc = data.deadline.astimezone(timezone.utc)
    if deadline_utc <= datetime.now(timezone.utc):
        raise InvalidDeadline("deadline must be in the future")
    if session.get(User, ALICE_ID) is None:
        raise RuntimeError("demo user Alice is unavailable")
    record = HelpRequest(
        requester_id=ALICE_ID,
        category="borrow",
        raw_text=public_text(data.raw_text) if data.raw_text else None,
        item_type=data.item_type.value,
        location=data.location,
        deadline=deadline_utc.replace(tzinfo=None),
        urgency=None,
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


def start_search(session: Session, request_id: int, actor_id: int, now: datetime | None = None, offer_message: str | None = None) -> HelpRequest:
    current = utc_naive(now)
    with write_transaction(session):
        request = _require_request(session, request_id)
        _require_requester(request, actor_id)
        if request.status == "awaiting_response":
            return request  # Retry does not send another Offer.
        if request.status != "draft":
            raise StateConflict("Only a draft request can start matching")
        if request.deadline <= current:
            transition(request, "expired")
            _event(session, request, "request_expired", "请求已到截止时间")
        else:
            transition(request, "searching")
            _event(session, request, "search_started", "正在寻找可用帮助者")
            _dispatch_next(session, request, current, offer_message)
        return request


def decline_offer(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_offer(session, offer_id, actor_id)
        request = offer.request
        if request.status in {"completed", "cancelled", "expired", "failed"}:
            raise StateConflict("Request is no longer active")
        if offer.status == "declined":
            return offer
        if offer.status != "pending" or request.status != "awaiting_response":
            raise StateConflict("Offer cannot be declined")
        if offer.expires_at <= current:
            _expire_offer_and_continue(session, offer, current)
            return offer
        offer.status = "declined"
        offer.responded_at = current
        _event(session, request, "offer_declined", f"{offer.helper.display_name} 已拒绝", str(offer.id))
        # Check the request deadline before searching for anybody else.
        if request.deadline <= current:
            transition(request, "expired")
            _event(session, request, "request_expired", "请求已到截止时间")
        else:
            transition(request, "searching")
            _dispatch_next(session, request, current)
        return offer


def accept_offer(session: Session, offer_id: int, actor_id: int, now: datetime | None = None) -> HelpOffer:
    current = utc_naive(now)
    with write_transaction(session):
        offer = _require_offer(session, offer_id, actor_id)
        request = offer.request
        if request.status in {"completed", "cancelled", "expired", "failed"}:
            raise StateConflict("Request is no longer active")
        if offer.status == "accepted":
            return offer
        if offer.status != "pending" or request.status != "awaiting_response":
            raise StateConflict("Offer cannot be accepted")
        if offer.expires_at <= current or request.deadline <= current:
            _expire_offer_and_continue(session, offer, current)
            return offer
        if not offer.item.available:
            raise StateConflict("Item is no longer available")
        offer.item.available = False
        offer.status = "accepted"
        offer.responded_at = current
        transition(request, "matched")
        _event(session, request, "offer_accepted", f"{offer.helper.display_name} 已接受；交接地点：{request.location}", str(offer.id))
        return offer


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
        _event(session, offer.request, "request_completed", "双方已确认，借物请求完成")


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
        offer = _pending_offer(session, request) or _accepted_offer(session, request)
        if offer is not None:
            if offer.status == "accepted":
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
                continue
            if request.status == "awaiting_response":
                offer = _pending_offer(session, request)
                if offer is not None and offer.expires_at <= current:
                    _expire_offer_and_continue(session, offer, current)
            elif request.status == "searching":
                _dispatch_next(session, request, current)


def list_helper_offers(session: Session, helper_id: int, actor_id: int) -> list[HelpOffer]:
    if actor_id != helper_id:
        raise Forbidden("Another helper's inbox is private")
    if session.get(User, helper_id) is None:
        raise NotFound("Helper not found")
    return session.scalars(select(HelpOffer).where(HelpOffer.helper_id == helper_id).order_by(HelpOffer.id.desc())).all()


def request_view(session: Session, request: HelpRequest):
    from app.schemas import EventRead, RequestRead

    events = session.scalars(select(AgentEvent).where(AgentEvent.request_id == request.id).order_by(AgentEvent.id)).all()
    accepted = _accepted_offer(session, request)
    return RequestRead.from_record(
        request,
        events=[EventRead.from_record(event) for event in events],
        matched_helper=accepted.helper.display_name if accepted else None,
        handoff_location=request.location if accepted else None,
        requester_confirmed=bool(accepted and accepted.requester_confirmed_at),
        helper_confirmed=bool(accepted and accepted.helper_confirmed_at),
    )
