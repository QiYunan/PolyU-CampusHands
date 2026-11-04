"""Deterministic item, availability, and campus travel-time matching."""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpOffer, HelpRequest, User, UserItem


TRAVEL_MINUTES = {
    frozenset(("VA", "PQ")): 5,
    frozenset(("VA", "LIBRARY")): 10,
    frozenset(("PQ", "LIBRARY")): 10,
}


def travel_minutes(origin: str, destination: str) -> int | None:
    origin = origin.strip().upper()
    destination = destination.strip().upper()
    if origin == destination:
        return 0
    return TRAVEL_MINUTES.get(frozenset((origin, destination)))


def rank_candidates(session: Session, request: HelpRequest, now: datetime) -> list[tuple[User, UserItem]]:
    contacted = set(session.scalars(select(HelpOffer.helper_id).where(HelpOffer.request_id == request.id)).all())
    rows = session.execute(
        select(User, UserItem)
        .join(UserItem, UserItem.user_id == User.id)
        .where(
            UserItem.item_type == request.item_type,
            UserItem.available.is_(True),
            User.availability_status == "available",
            User.id != request.requester_id,
        )
    ).all()
    ranked = []
    for helper, item in rows:
        minutes = travel_minutes(request.location, helper.campus_building)
        if helper.id in contacted or minutes is None or now + timedelta(minutes=minutes) > request.deadline:
            continue
        ranked.append((minutes, helper.id, item.id, helper, item))
    ranked.sort(key=lambda row: row[:3])
    # At most one Offer per helper for a request, even if they own several matching items.
    chosen = []
    seen_helpers = set()
    for _, _, _, helper, item in ranked:
        if helper.id not in seen_helpers:
            chosen.append((helper, item))
            seen_helpers.add(helper.id)
    return chosen
