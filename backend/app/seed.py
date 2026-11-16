"""Repeatable fictional demo fixtures. Never overwrites existing records."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import HelpRequest, User, UserItem


DEMO_HELPERS = (
    # id, display name, building, availability, internal reliability, item type,
    # item name, brand, model, and item availability. All identities are fictional.
    (2, "Bob", "VA", "available", 0.70, "scientific_calculator", "Scientific calculator", None, None, True),
    (3, "Carol", "PQ", "available", 0.60, "scientific_calculator", "Scientific calculator", None, None, True),
    (4, "David", "L", "available", 0.40, "charger", "USB-C charger", None, None, True),
    (5, "Erin", "Z", "available", 0.95, "scientific_calculator", "Casio fx-991EX scientific calculator", "Casio", "fx-991EX", True),
    (6, "Felix", "L", "available", 0.80, "scientific_calculator", "Generic scientific calculator", None, None, True),
    (7, "Grace", "Y", "available", 0.50, "scientific_calculator", "Casio fx-991EX scientific calculator", "Casio", "fx-991EX", True),
    (8, "Hana", "N", "available", 0.70, "scientific_calculator", "Unavailable scientific calculator", None, None, False),
    (9, "Ivan", "L", "available", 0.85, "charger", "Compact USB-C charger", None, None, True),
    (10, "June", "L", "available", 0.55, "charger", "Spare USB-C charger", None, None, True),
    (11, "Kai", "Q", "unavailable", 0.80, "adapter", "USB-C adapter", None, None, True),
    (12, "Lea", "A", "available", 0.65, "umbrella", "Umbrella", None, None, True),
)
SEED_REQUEST_TEXT = "BorrowLoop demo seed: scientific calculator"


def seed_demo_people(session: Session) -> None:
    for user_id, name, building, status, reliability, item_type, item_name, brand, model, available in DEMO_HELPERS:
        user = session.get(User, user_id)
        if user is None:
            session.add(User(id=user_id, display_name=name, campus_building=building,
                             availability_status=status, reliability_score=reliability))
            session.flush()
        elif user.display_name != name:
            raise RuntimeError(f"Demo user ID {user_id} belongs to another user")
        item = session.scalar(select(UserItem).where(UserItem.user_id == user_id, UserItem.item_type == item_type, UserItem.item_name == item_name))
        if item is None:
            session.add(UserItem(user_id=user_id, item_type=item_type, item_name=item_name,
                                 brand=brand, model=model, available=available))
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
