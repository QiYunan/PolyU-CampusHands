"""SQLite session setup and the repeatable local demo user."""

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, inspect
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


def _make_help_offer_item_optional(connection, schema) -> None:
    """Rebuild legacy SQLite Offer tables whose item_id was NOT NULL.

    SQLite cannot relax a column constraint with ALTER TABLE. The rebuild runs
    inside initialize_database's immediate transaction and copies every legacy
    row before the old table is replaced.
    """
    if not schema.has_table("help_offers"):
        return
    columns = {column["name"]: column for column in schema.get_columns("help_offers")}
    if columns.get("item_id", {}).get("nullable", True):
        return

    def source(name: str, fallback: str = "NULL") -> str:
        return name if name in columns else fallback

    connection.exec_driver_sql("DROP TABLE IF EXISTS help_offers__m06")
    connection.exec_driver_sql(
        "CREATE TABLE help_offers__m06 ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "request_id INTEGER NOT NULL, "
        "helper_id INTEGER NOT NULL, "
        "item_id INTEGER, "
        "message VARCHAR(300), "
        "response_type VARCHAR(32) NOT NULL DEFAULT 'direct', "
        "help_note VARCHAR(300), "
        "offered_brand VARCHAR(80), "
        "offered_model VARCHAR(80), "
        "capability_confirmed_at DATETIME, "
        "status VARCHAR(32) NOT NULL, "
        "sent_at DATETIME NOT NULL, "
        "responded_at DATETIME, "
        "expires_at DATETIME NOT NULL, "
        "requester_confirmed_at DATETIME, "
        "helper_confirmed_at DATETIME, "
        "CONSTRAINT uq_offer_request_helper UNIQUE (request_id, helper_id), "
        "FOREIGN KEY(request_id) REFERENCES help_requests (id), "
        "FOREIGN KEY(helper_id) REFERENCES users (id), "
        "FOREIGN KEY(item_id) REFERENCES user_items (id)"
        ")"
    )
    capability_fallback = (
        "CASE WHEN status IN ('accepted', 'proposed') "
        f"THEN COALESCE({source('responded_at')}, sent_at) END"
    )
    connection.exec_driver_sql(
        "INSERT INTO help_offers__m06 ("
        "id, request_id, helper_id, item_id, message, response_type, help_note, "
        "offered_brand, offered_model, capability_confirmed_at, status, sent_at, "
        "responded_at, expires_at, requester_confirmed_at, helper_confirmed_at"
        ") SELECT "
        f"id, request_id, helper_id, item_id, {source('message')}, "
        f"COALESCE({source('response_type')}, 'direct'), "
        f"COALESCE({source('help_note')}, {source('message')}), "
        f"{source('offered_brand')}, {source('offered_model')}, "
        f"COALESCE({source('capability_confirmed_at')}, {capability_fallback}), "
        f"status, sent_at, {source('responded_at')}, expires_at, "
        f"{source('requester_confirmed_at')}, {source('helper_confirmed_at')} "
        "FROM help_offers"
    )
    connection.exec_driver_sql("DROP TABLE help_offers")
    connection.exec_driver_sql("ALTER TABLE help_offers__m06 RENAME TO help_offers")


def initialize_database(engine) -> None:
    from app.models import User  # Import before create_all so tables are registered.

    Base.metadata.create_all(engine)
    # SQLite create_all does not add columns to tables from earlier milestones.
    # A single immediate transaction serializes the schema check and additions
    # with other local startup processes. All identifiers below are constants.
    additions = {
        "help_offers": {
            "message": "VARCHAR(300)",
            "response_type": "VARCHAR(32) DEFAULT 'direct'",
            "help_note": "VARCHAR(300)",
            "offered_brand": "VARCHAR(80)",
            "offered_model": "VARCHAR(80)",
            "capability_confirmed_at": "DATETIME",
            "invitation_id": "INTEGER",
            "service_capability_id": "INTEGER",
        },
        "help_requests": {
            "category": "VARCHAR(32) DEFAULT 'borrow'",
            "need_summary": "VARCHAR(200)",
            "urgency": "VARCHAR(32) DEFAULT 'normal'",
            "preferred_brand": "VARCHAR(80)",
            "preferred_model": "VARCHAR(80)",
            "substitution_policy": "VARCHAR(32)",
            "matching_issue": "VARCHAR(64)",
            "service_code": "VARCHAR(32)",
            "service_name": "VARCHAR(120)",
        },
        "help_request_drafts": {
            "category": "VARCHAR(32) DEFAULT 'borrow'",
            "need_summary": "VARCHAR(200)",
            "urgency": "VARCHAR(32)",
            "preferred_brand": "VARCHAR(80)",
            "preferred_model": "VARCHAR(80)",
            "substitution_policy": "VARCHAR(32)",
            "service_code": "VARCHAR(32)",
            "service_name": "VARCHAR(120)",
        },
        "user_items": {
            "brand": "VARCHAR(80)",
            "model": "VARCHAR(80)",
            "is_active": "BOOLEAN DEFAULT 1",
        },
    }
    with engine.connect() as connection:
        try:
            if engine.dialect.name == "sqlite":
                # A legacy database can contain rows created before foreign-key
                # enforcement was enabled. Keep those rows while rebuilding the
                # Offer table, then restore enforcement for all future writes.
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            schema = inspect(connection)
            if engine.dialect.name == "sqlite":
                _make_help_offer_item_optional(connection, schema)
                schema = inspect(connection)
            for table, columns in additions.items():
                existing = {column["name"] for column in schema.get_columns(table)}
                for name, sql_type in columns.items():
                    if name not in existing:
                        connection.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")
            # Existing rows had no structured preference, so retain their old
            # category-only matching behavior without parsing historical text.
            for table in ("help_requests", "help_request_drafts"):
                connection.exec_driver_sql(
                    f"UPDATE {table} SET substitution_policy = 'equivalent_ok' "
                    "WHERE substitution_policy IS NULL"
                )
            connection.exec_driver_sql(
                "UPDATE help_requests SET category = 'borrow' WHERE category IS NULL OR TRIM(category) = ''"
            )
            connection.exec_driver_sql(
                "UPDATE help_request_drafts SET category = 'borrow' WHERE category IS NULL OR TRIM(category) = ''"
            )
            for table in ("help_requests", "help_request_drafts"):
                connection.exec_driver_sql(
                    f"UPDATE {table} SET need_summary = CASE item_type "
                    "WHEN 'scientific_calculator' THEN '科学计算器' "
                    "WHEN 'charger' THEN '充电器' "
                    "WHEN 'adapter' THEN '转接头' "
                    "WHEN 'stationery' THEN '文具' "
                    "WHEN 'umbrella' THEN '雨伞' "
                    "ELSE COALESCE(NULLIF(TRIM(raw_text), ''), '校园求助') END "
                    "WHERE need_summary IS NULL OR TRIM(need_summary) = ''"
                )
            connection.exec_driver_sql(
                "UPDATE help_requests SET urgency = 'normal' WHERE urgency IS NULL OR TRIM(urgency) = ''"
            )
            connection.exec_driver_sql(
                "UPDATE help_offers SET response_type = 'direct' "
                "WHERE response_type IS NULL OR TRIM(response_type) = ''"
            )
            connection.exec_driver_sql(
                "UPDATE help_offers SET help_note = message WHERE help_note IS NULL AND message IS NOT NULL"
            )
            connection.exec_driver_sql(
                "UPDATE help_offers SET capability_confirmed_at = COALESCE(responded_at, sent_at) "
                "WHERE capability_confirmed_at IS NULL AND status IN ('accepted', 'proposed')"
            )
            connection.exec_driver_sql(
                "UPDATE user_items SET is_active = 1 WHERE is_active IS NULL"
            )
            for table in ("help_requests", "help_request_drafts"):
                connection.exec_driver_sql(
                    f"UPDATE {table} SET service_code = 'other', "
                    "service_name = COALESCE(NULLIF(TRIM(need_summary), ''), '校园服务') "
                    "WHERE category = 'service' AND service_code IS NULL"
                )
            # Claim writes run under BEGIN IMMEDIATE. These partial indexes also
            # defend the invariant if a future caller bypasses the service.
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_accepted_offer_request "
                    "ON help_offers (request_id) WHERE status = 'accepted'"
                )
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_accepted_offer_item "
                    "ON help_offers (item_id) WHERE status = 'accepted' AND item_id IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_help_offer_invitation "
                    "ON help_offers (invitation_id) WHERE invitation_id IS NOT NULL"
                )
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_open_invitation_batch "
                    "ON invitation_batches (request_id) WHERE status = 'open'"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    with Session(engine) as session:
        if session.get(User, ALICE_ID) is None:
            session.add(User(id=ALICE_ID, display_name="Alice", campus_building="VA", availability_status="unknown"))
            session.commit()
