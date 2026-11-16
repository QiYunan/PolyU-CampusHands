"""Deterministic M07 matching over long-term capabilities and today's supply."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.campus_locations import travel_minutes
from app.matching import HANDOFF_BUFFER_MINUTES, preference_key
from app.models import (
    DailyAvailability,
    DailyAvailableItem,
    DailyAvailableService,
    HelpInvitation,
    HelpOffer,
    HelpRequest,
    User,
    UserItem,
    UserServiceCapability,
)


HONG_KONG = timezone(timedelta(hours=8), name="Asia/Hong_Kong")


@dataclass(frozen=True)
class SupplyCandidate:
    helper: User
    availability: DailyAvailability
    item: UserItem | None
    service: UserServiceCapability | None
    match_reason: str
    estimated_arrival_minutes: int
    is_substitute: bool
    recent_task_count: int


@dataclass(frozen=True)
class SupplySearchResult:
    candidates: list[SupplyCandidate]
    issue: str | None = None


def utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _normalized_name(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _item_tier(item: UserItem, request: HelpRequest) -> tuple[int, str]:
    brand = preference_key(request.preferred_brand)
    model = preference_key(request.preferred_model)
    item_brand = preference_key(item.brand)
    item_model = preference_key(item.model)
    if model is not None and item_model == model and (brand is None or item_brand == brand):
        return 0, "exact_model"
    if brand is not None and item_brand == brand:
        return 1, "exact_brand"
    return 2, "compatible"


def _required_tier(request: HelpRequest) -> int:
    if preference_key(request.preferred_model) is not None:
        return 0
    if preference_key(request.preferred_brand) is not None:
        return 1
    return 2


def reliability_level(score: float | None) -> str:
    try:
        number = float(score) if score is not None else float("nan")
    except (TypeError, ValueError, OverflowError):
        number = float("nan")
    if not math.isfinite(number):
        return "New"
    if number >= 0.85:
        return "A"
    if number >= 0.65:
        return "B"
    return "C"


def _active_helper_ids(session: Session) -> set[int]:
    return set(session.scalars(
        select(HelpOffer.helper_id)
        .join(HelpRequest, HelpRequest.id == HelpOffer.request_id)
        .where(HelpOffer.status == "accepted", HelpRequest.status.in_(("matched", "in_progress")))
    ).all())


def _occupied_item_ids(session: Session) -> set[int]:
    return {
        item_id for item_id in session.scalars(
            select(HelpOffer.item_id)
            .join(HelpRequest, HelpRequest.id == HelpOffer.request_id)
            .where(
                HelpOffer.status == "accepted",
                HelpOffer.item_id.is_not(None),
                HelpRequest.status.in_(("matched", "in_progress")),
            )
        ).all()
        if item_id is not None
    }


def _declined_helper_ids(session: Session, request_id: int) -> set[int]:
    return set(session.scalars(select(HelpInvitation.helper_id).where(
        HelpInvitation.request_id == request_id,
        HelpInvitation.status == "declined",
        HelpInvitation.decline_reason.in_(("declined", "cannot_arrive")),
    )).all())


def _recent_task_counts(session: Session, now: datetime) -> dict[int, int]:
    since = utc_naive(now) - timedelta(days=7)
    rows = session.execute(
        select(HelpOffer.helper_id, func.count(HelpOffer.id))
        .where(HelpOffer.status == "accepted", HelpOffer.sent_at >= since)
        .group_by(HelpOffer.helper_id)
    ).all()
    return {helper_id: count for helper_id, count in rows}


def _item_for_daily(
    session: Session,
    daily: DailyAvailability,
    request: HelpRequest,
    occupied: set[int],
) -> tuple[UserItem | None, str | None, bool]:
    items = session.scalars(
        select(UserItem)
        .join(DailyAvailableItem, DailyAvailableItem.item_id == UserItem.id)
        .where(
            DailyAvailableItem.daily_availability_id == daily.id,
            UserItem.user_id == daily.user_id,
            UserItem.item_type == request.item_type,
            UserItem.is_active.is_(True),
            UserItem.available.is_(True),
        )
        .order_by(UserItem.id)
    ).all()
    usable = [item for item in items if item.id not in occupied]
    if not usable:
        return None, None, False
    ranked = sorted(((*_item_tier(item, request), item) for item in usable), key=lambda row: (row[0], row[2].id))
    tier, reason, item = ranked[0]
    required = _required_tier(request)
    policy = request.substitution_policy or "equivalent_ok"
    if policy == "exact_only" and tier != required:
        return None, None, False
    return item, reason, required < 2 and tier != required


def _service_for_daily(
    session: Session,
    daily: DailyAvailability,
    request: HelpRequest,
) -> UserServiceCapability | None:
    services = session.scalars(
        select(UserServiceCapability)
        .join(DailyAvailableService, DailyAvailableService.service_id == UserServiceCapability.id)
        .where(
            DailyAvailableService.daily_availability_id == daily.id,
            UserServiceCapability.user_id == daily.user_id,
            UserServiceCapability.active.is_(True),
            UserServiceCapability.service_code == (request.service_code or "other"),
        )
        .order_by(UserServiceCapability.id)
    ).all()
    if (request.service_code or "other") == "other":
        target = _normalized_name(request.service_name or request.need_summary)
        services = [service for service in services if _normalized_name(service.service_name) == target]
    return services[0] if services else None


def search_supply_candidates(
    session: Session,
    request: HelpRequest,
    now: datetime,
) -> SupplySearchResult:
    current = utc_naive(now)
    local_date = current.replace(tzinfo=timezone.utc).astimezone(HONG_KONG).date()
    daily_rows = session.scalars(
        select(DailyAvailability).where(
            DailyAvailability.local_date == local_date,
            DailyAvailability.willing.is_(True),
            DailyAvailability.user_id != request.requester_id,
        ).order_by(DailyAvailability.user_id)
    ).all()
    if not daily_rows:
        return SupplySearchResult([], "no_today_availability")

    active_helpers = _active_helper_ids(session)
    occupied_items = _occupied_item_ids(session)
    declined_helpers = _declined_helper_ids(session, request.id)
    recent_counts = _recent_task_counts(session, current)
    deadline = utc_naive(request.deadline)
    capability_seen = False
    timely_seen = False
    ranked: list[tuple[tuple, SupplyCandidate]] = []

    for daily in daily_rows:
        helper = session.get(User, daily.user_id)
        if helper is None or helper.id in active_helpers or helper.id in declined_helpers:
            continue
        if request.urgency == "high" and not daily.accepts_urgent:
            continue
        if daily.available_until < deadline:
            continue

        item = None
        service = None
        reason = None
        is_substitute = False
        if request.category == "borrow":
            item, reason, is_substitute = _item_for_daily(session, daily, request, occupied_items)
            if item is None:
                continue
        else:
            service = _service_for_daily(session, daily, request)
            if service is None:
                continue
            reason = "service_exact"
        capability_seen = True

        walk = travel_minutes(daily.campus_building, request.location)
        if walk is None:
            continue
        departure = max(current, daily.available_from)
        arrival = departure + timedelta(minutes=walk + HANDOFF_BUFFER_MINUTES)
        if arrival > deadline:
            continue
        timely_seen = True
        arrival_minutes = max(0, math.ceil((arrival - current).total_seconds() / 60))
        task_count = recent_counts.get(helper.id, 0)
        score = helper.reliability_score
        score_key = -float(score) if score is not None and math.isfinite(float(score)) else float("inf")
        tier = {"exact_model": 0, "exact_brand": 1, "service_exact": 0, "compatible": 2}[reason]
        slack = (daily.available_until - deadline).total_seconds()
        candidate = SupplyCandidate(
            helper=helper,
            availability=daily,
            item=item,
            service=service,
            match_reason=reason,
            estimated_arrival_minutes=arrival_minutes,
            is_substitute=is_substitute,
            recent_task_count=task_count,
        )
        ranked.append(((tier, arrival_minutes, -slack, score_key, task_count, helper.id), candidate))

    if not ranked:
        if not capability_seen:
            return SupplySearchResult([], "no_matching_capability")
        if not timely_seen:
            return SupplySearchResult([], "unreachable_before_deadline")
        return SupplySearchResult([], "candidate_exhausted")
    ranked.sort(key=lambda row: row[0])
    return SupplySearchResult([candidate for _, candidate in ranked])


def candidate_for_helper(
    session: Session,
    request: HelpRequest,
    helper_id: int,
    now: datetime,
) -> SupplyCandidate | None:
    result = search_supply_candidates(session, request, now)
    return next((candidate for candidate in result.candidates if candidate.helper.id == helper_id), None)
