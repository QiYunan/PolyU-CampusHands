"""SQLite session setup and the repeatable local demo user."""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


DEFAULT_DATABASE_URL = f"sqlite:///{(Path(__file__).resolve().parents[1] / 'campushands.db').as_posix()}"
ALICE_ID = 1


class Base(DeclarativeBase):
    pass


def utc_now_naive() -> datetime:
    """Store UTC as naive datetimes because SQLite has no timezone type."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str):
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(engine) -> None:
    from app.models import User  # Import before create_all so tables are registered.

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.get(User, ALICE_ID) is None:
            session.add(User(id=ALICE_ID, display_name="Alice", campus_building="VA", availability_status="unknown"))
            session.commit()
