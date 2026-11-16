"""Legacy inventory diagnostics plus current Helper declaration comparison.

The inventory/location helpers remain only for historical data compatibility.
The open-board service must not use them to decide whether a Helper may respond.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.campus_locations import normalize_location, travel_minutes
from app.models import HelpOffer, HelpRequest, User, UserItem


HANDOFF_BUFFER_MINUTES = 3
_POLICIES = {"ask_before_substitute", "exact_only", "equivalent_ok"}


@dataclass(frozen=True)
class MatchResult:
    candidates: list[tuple[User, UserItem, int]]
    issue: str | None = None


@dataclass(frozen=True)
class HelperEligibility:
    can_claim: bool
    match_tier: str | None
    item: UserItem | None
    walk_minutes: int | None
    safe_reason: str | None


_TIER_NAMES = ("exact_model", "exact_brand", "compatible")


def _preference_key(value: str | None) -> str | None:
    if value is None:
        return None
    # Brand/model punctuation and spacing vary in ordinary user input
    # (for example ``fx-991cnx`` versus ``FX 991CNX``).
    key = re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold())
    return key or None


def _item_tier(item: UserItem, brand: str | None, model: str | None) -> int:
    item_brand = _preference_key(item.brand)
    item_model = _preference_key(item.model)
    if model is not None and item_model == model and (brand is None or item_brand == brand):
        return 0  # Requested model, and requested brand if supplied.
    if brand is not None and item_brand == brand:
        return 1  # Requested brand, but not requested model.
    return 2  # Same compatible item category.


def _exact_tier(brand: str | None, model: str | None) -> int:
    if model is not None:
        return 0
    if brand is not None:
        return 1
    return 2


def _reliability_key(score: float | None) -> tuple[bool, float]:
    try:
        number = float(score) if score is not None else float("nan")
    except (TypeError, ValueError, OverflowError):
        number = float("nan")
    return (False, -number) if math.isfinite(number) else (True, 0.0)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def preference_key(value: str | None) -> str | None:
    """Normalize a user-entered brand or model for exact comparison."""

    return _preference_key(value)


def offered_item_matches(
    request: HelpRequest,
    offered_brand: str | None,
    offered_model: str | None,
) -> bool:
    """Return whether a Helper declaration satisfies every stated preference."""

    requested_brand = _preference_key(request.preferred_brand)
    requested_model = _preference_key(request.preferred_model)
    brand = _preference_key(offered_brand)
    model = _preference_key(offered_model)
    return (
        (requested_brand is None or brand == requested_brand)
        and (requested_model is None or model == requested_model)
    )


def evaluate_helper(session: Session, request: HelpRequest, helper: User, now: datetime) -> HelperEligibility:
    """Evaluate only this Helper's own items. The service reuses this at claim time.

    Neither the selected item nor walking minutes may enter a public board row;
    they are internal facts used for qualification and ordering only.
    """
    if request.status != "awaiting_response":
        return HelperEligibility(False, None, None, None, "request_closed")
    if helper.id == request.requester_id:
        return HelperEligibility(False, None, None, None, "no_item")

    items = session.scalars(select(UserItem).where(
        UserItem.user_id == helper.id, UserItem.item_type == request.item_type,
    ).order_by(UserItem.id)).all()
    if not items:
        return HelperEligibility(False, None, None, None, "no_item")
    occupied = set(session.scalars(select(HelpOffer.item_id).join(
        UserItem, UserItem.id == HelpOffer.item_id,
    ).where(UserItem.user_id == helper.id, HelpOffer.status == "accepted")).all())
    usable = [item for item in items if item.available and item.id not in occupied]
    if not usable:
        return HelperEligibility(False, None, None, None, "no_item")

    brand = _preference_key(request.preferred_brand)
    model = _preference_key(request.preferred_model)
    item = min(usable, key=lambda candidate: (_item_tier(candidate, brand, model), candidate.id))
    tier = _item_tier(item, brand, model)
    tier_name = _TIER_NAMES[tier]
    if helper.availability_status != "available":
        return HelperEligibility(False, tier_name, item, None, "helper_unavailable")

    minutes = travel_minutes(helper.campus_building, request.location)
    if minutes is None:
        return HelperEligibility(False, tier_name, item, None, "unknown_location")
    if _utc_naive(now) + timedelta(minutes=minutes + HANDOFF_BUFFER_MINUTES) > _utc_naive(request.deadline):
        return HelperEligibility(False, tier_name, item, minutes, "unreachable_before_deadline")

    exact_tier = _exact_tier(brand, model)
    policy = request.substitution_policy or "equivalent_ok"
    if policy not in _POLICIES:
        policy = "exact_only"  # Invalid stored data never grants substitution.
    if exact_tier < 2 and tier != exact_tier and policy != "equivalent_ok":
        reason = "substitution_needs_confirmation" if policy == "ask_before_substitute" else "exact_preference_unavailable"
        return HelperEligibility(False, tier_name, item, minutes, reason)
    return HelperEligibility(True, tier_name, item, minutes, None)


def evaluate_candidates(session: Session, request: HelpRequest, now: datetime) -> MatchResult:
    """Read-only publication precheck; no result here assigns a request.

    The result remains internal to the service layer. It contains private User
    and UserItem objects and must never be serialized into API, Agent or WS
    observations. The public API may use ``issue`` but no candidate details.
    """
    handoff = normalize_location(request.location)
    if handoff is None:
        return MatchResult([], "unknown_location")

    # Query all same-category helper items so the issue distinguishes an empty
    # inventory from unavailable items and unavailable helpers. No name-text
    # inference or provider score participates in matching.
    rows = session.execute(
        select(User, UserItem)
        .join(UserItem, UserItem.user_id == User.id)
        .where(UserItem.item_type == request.item_type, User.id != request.requester_id)
    ).all()
    with_item = [(helper, item) for helper, item in rows if item.available]
    if not with_item:
        return MatchResult([], "no_item_inventory")

    available = [
        (helper, item) for helper, item in with_item
        if helper.availability_status == "available"
    ]
    if not available:
        return MatchResult([], "no_available_helper")

    brand = _preference_key(request.preferred_brand)
    model = _preference_key(request.preferred_model)
    exact_tier = _exact_tier(brand, model)
    policy = request.substitution_policy or "equivalent_ok"
    if policy not in _POLICIES:
        policy = "exact_only"  # Invalid stored policy must never grant substitution.

    contacted = set(session.scalars(
        select(HelpOffer.helper_id).where(HelpOffer.request_id == request.id)
    ).all()) if request.id is not None else set()
    deadline = _utc_naive(request.deadline)
    current = _utc_naive(now)
    routed: list[tuple[User, UserItem, int, int, bool]] = []
    for helper, item in available:
        minutes = travel_minutes(handoff, helper.campus_building)
        if minutes is None:
            continue
        timely = current + timedelta(minutes=minutes + HANDOFF_BUFFER_MINUTES) <= deadline
        routed.append((helper, item, minutes, _item_tier(item, brand, model), timely))
    if not routed:
        return MatchResult([], "no_available_helper")

    uncontacted = [row for row in routed if row[0].id not in contacted]
    if not uncontacted:
        return MatchResult([], "candidate_exhausted")

    if policy == "exact_only" and exact_tier < 2:
        relevant = [row for row in uncontacted if row[3] == exact_tier]
        if not relevant:
            # A prior exact Offer may have exhausted an otherwise viable
            # preference. Generic inventory does not satisfy exact_only.
            contacted_exact = any(
                row[0].id in contacted and row[3] == exact_tier and row[4]
                for row in routed
            )
            return MatchResult([], "candidate_exhausted" if contacted_exact else "exact_preference_unavailable")
        timely_rows = [row for row in relevant if row[4]]
        if not timely_rows:
            # Exact-only has no feasible exact candidate even if matching
            # inventory exists at a location that cannot meet the deadline.
            return MatchResult([], "exact_preference_unavailable")
    elif policy == "ask_before_substitute" and exact_tier < 2:
        timely_rows = [row for row in uncontacted if row[4] and row[3] == exact_tier]
        if not timely_rows:
            # Confirmation is requested only for a real uncontacted substitute
            # that passes the same route and deadline checks as an exact item.
            if any(row[4] and row[3] != exact_tier for row in uncontacted):
                return MatchResult([], "alternatives_available_needs_confirmation")
            return MatchResult([], "unreachable_before_deadline")
    else:
        timely_rows = [row for row in uncontacted if row[4]]
        if not timely_rows:
            return MatchResult([], "unreachable_before_deadline")

    ranked = []
    for helper, item, minutes, tier, _ in timely_rows:
        missing_score, negative_score = _reliability_key(helper.reliability_score)
        ranked.append((tier, minutes, missing_score, negative_score, helper.id, item.id, helper, item))
    ranked.sort(key=lambda row: row[:6])

    chosen: list[tuple[User, UserItem, int]] = []
    seen_helpers: set[int] = set()
    for _, minutes, _, _, _, _, helper, item in ranked:
        if helper.id not in seen_helpers:
            chosen.append((helper, item, minutes))
            seen_helpers.add(helper.id)
    return MatchResult(chosen)


def rank_candidates(session: Session, request: HelpRequest, now: datetime) -> list[tuple[User, UserItem]]:
    """Compatibility adapter for callers that only consume ordered pairs."""
    return [(helper, item) for helper, item, _ in evaluate_candidates(session, request, now).candidates]
