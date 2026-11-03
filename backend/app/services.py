"""Milestone 01 request rules and persistence."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.database import ALICE_ID
from app.models import HelpRequest, User
from app.schemas import RequestCreate


class InvalidDeadline(ValueError):
    pass


def create_request(session: Session, data: RequestCreate) -> HelpRequest:
    deadline_utc = data.deadline.astimezone(timezone.utc)
    if deadline_utc <= datetime.now(timezone.utc):
        raise InvalidDeadline("deadline must be in the future")
    if session.get(User, ALICE_ID) is None:
        raise RuntimeError("demo user Alice is unavailable")
    record = HelpRequest(
        requester_id=ALICE_ID,
        category="borrow",
        raw_text=data.raw_text,
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
