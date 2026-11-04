"""Repeatable fictional demo fixtures. Never overwrites existing records."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpRequest, User, UserItem


DEMO_HELPERS = (
    (2, "Bob", "VA", "scientific_calculator", "Scientific calculator"),
    (3, "Carol", "PQ", "scientific_calculator", "Scientific calculator"),
    (4, "David", "Library", "charger", "USB-C charger"),
)
SEED_REQUEST_TEXT = "BorrowLoop demo seed: scientific calculator"


def seed_demo_people(session: Session) -> None:
    for user_id, name, building, item_type, item_name in DEMO_HELPERS:
        user = session.get(User, user_id)
        if user is None:
            session.add(User(id=user_id, display_name=name, campus_building=building, availability_status="available"))
            session.flush()
        elif user.display_name != name:
            raise RuntimeError(f"Demo user ID {user_id} belongs to another user")
        item = session.scalar(select(UserItem).where(UserItem.user_id == user_id, UserItem.item_type == item_type, UserItem.item_name == item_name))
        if item is None:
            session.add(UserItem(user_id=user_id, item_type=item_type, item_name=item_name, available=True))
    session.commit()


def seed_demo_request(session: Session) -> HelpRequest:
    existing = session.scalar(select(HelpRequest).where(HelpRequest.requester_id == 1, HelpRequest.raw_text == SEED_REQUEST_TEXT))
    if existing is not None:
        return existing
    request = HelpRequest(
        requester_id=1,
        category="borrow",
        raw_text=SEED_REQUEST_TEXT,
        item_type="scientific_calculator",
        location="VA",
        deadline=(datetime.now(timezone.utc) + timedelta(minutes=20)).replace(tzinfo=None),
        urgency=None,
        status="draft",
    )
    session.add(request)
    session.commit()
    session.refresh(request)
    return request


def main() -> None:
    from app.database import database_url, initialize_database, make_engine

    engine = make_engine(database_url())
    try:
        initialize_database(engine)
        with Session(engine) as session:
            seed_demo_people(session)
            request = seed_demo_request(session)
            print(f"Demo request ID: {request.id}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
