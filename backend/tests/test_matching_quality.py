"""Milestone 06 offline location, migration, and matching contracts."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campus_locations import location_options, normalize_location, travel_minutes
from app.database import initialize_database, make_engine
from app.matching import HANDOFF_BUFFER_MINUTES, evaluate_candidates, rank_candidates
from app.models import HelpOffer, HelpRequest, User, UserItem


NOW = datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'matching.db').as_posix()}")
    initialize_database(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def add_helper(db, user_id, building, *, item_type="scientific_calculator", brand=None,
               model=None, available=True, helper_status="available", reliability=None,
               item_name=None):
    helper = db.get(User, user_id)
    if helper is None:
        helper = User(id=user_id, display_name=f"Helper {user_id}", campus_building=building,
                      availability_status=helper_status, reliability_score=reliability)
        db.add(helper)
    item = UserItem(user_id=user_id, item_type=item_type,
                    item_name=item_name or f"Item {user_id}", brand=brand, model=model,
                    available=available)
    db.add(item)
    db.flush()
    return helper, item


def add_request(db, *, location="Z", minutes=30, brand=None, model=None,
                policy="equivalent_ok", item_type="scientific_calculator"):
    request = HelpRequest(requester_id=1, category="borrow", item_type=item_type,
                          preferred_brand=brand, preferred_model=model,
                          substitution_policy=policy, location=location,
                          deadline=NOW + timedelta(minutes=minutes), status="draft")
    db.add(request)
    db.flush()
    return request


def contact(db, request, helper, item):
    db.add(HelpOffer(request_id=request.id, helper_id=helper.id, item_id=item.id,
                     status="declined", sent_at=NOW,
                     expires_at=NOW + timedelta(minutes=5)))
    db.flush()


@pytest.mark.parametrize("alias", ["Z", "z栋", "Z棟", "Z座", "Block Z", "Ｚ座"])
def test_z_aliases_have_identical_paths(alias):
    assert normalize_location(alias) == "Z"
    assert travel_minutes(alias, "Library") == travel_minutes("Z", "L")


@pytest.mark.parametrize("alias", ["Library", "LIBRARY", "图书馆", "圖書館", "Pao Yue-kong Library", "University Library"])
def test_library_aliases(alias):
    assert normalize_location(alias) == "L"


@pytest.mark.parametrize("alias,code", [
    ("Shaw Amenities Building", "VA"), ("邵逸夫楼", "VA"),
    ("Shaw Sports Complex", "VS"), ("邵逸夫體育館", "VS"),
    ("Jockey Club Innovation Tower", "V"), ("赛马会创新楼", "V"),
    ("Lee Shau Kee Building", "Y"), ("李兆基樓", "Y"),
])
def test_named_building_aliases(alias, code):
    assert normalize_location(alias) == code


def test_graph_is_connected_and_never_accepts_unknown_equal_text():
    codes = [option["code"] for option in location_options()]
    assert len(codes) == len(set(codes))
    assert all(travel_minutes(first, second) is not None for first in codes for second in codes)
    assert travel_minutes("unknown tower", "unknown tower") is None
    assert normalize_location("Z9") is None
    assert travel_minutes("Z", "Z") == 0
    assert travel_minutes("VA", "PQ") < travel_minutes("VA", "L")


def test_exact_model_then_brand_then_compatible_before_distance(session):
    generic, generic_item = add_helper(session, 2, "Z")
    brand, brand_item = add_helper(session, 3, "Y", brand="Casio")
    model, model_item = add_helper(session, 4, "L", brand="ＣＡＳＩＯ", model="FX 991 EX")
    request = add_request(session, brand="casio", model="fx991ex", minutes=40)
    result = evaluate_candidates(session, request, NOW)
    assert result.issue is None
    assert [helper.id for helper, _, _ in result.candidates] == [model.id, brand.id, generic.id]
    assert [item.id for _, item, _ in result.candidates] == [model_item.id, brand_item.id, generic_item.id]
    assert [helper.id for helper, _ in rank_candidates(session, request, NOW)] == [4, 3, 2]


def test_best_item_per_helper_and_stable_reliability_id_ties(session):
    first, item_low = add_helper(session, 2, "Z", brand="Casio", reliability=0.7,
                                 item_name="Casio A")
    _, item_high = add_helper(session, 2, "Z", brand="Casio", reliability=0.7,
                              item_name="Casio B")
    high, _ = add_helper(session, 3, "Z", brand="Casio", reliability=0.9)
    low, _ = add_helper(session, 4, "Z", brand="Casio", reliability=0.2)
    unknown, _ = add_helper(session, 5, "Z", brand="Casio", reliability=None)
    infinite, _ = add_helper(session, 6, "Z", brand="Casio", reliability=float("inf"))
    request = add_request(session, brand="Casio", policy="equivalent_ok")
    result = evaluate_candidates(session, request, NOW)
    assert [helper.id for helper, _, _ in result.candidates] == [high.id, first.id, low.id, unknown.id, infinite.id]
    assert next(item.id for helper, item, _ in result.candidates if helper.id == first.id) == item_low.id
    assert item_high.id != item_low.id


def test_helper_id_is_final_tie_break(session):
    add_helper(session, 9, "Z", reliability=0.5)
    add_helper(session, 7, "Z", reliability=0.5)
    request = add_request(session)
    assert [helper.id for helper, _, _ in evaluate_candidates(session, request, NOW).candidates] == [7, 9]


def test_unknown_handoff_and_unusable_item_never_offer(session):
    add_helper(session, 2, "Z", available=False)
    unknown = add_request(session, location="Unknown Building")
    assert evaluate_candidates(session, unknown, NOW).issue == "unknown_location"
    request = add_request(session)
    assert evaluate_candidates(session, request, NOW).issue == "no_item_inventory"


def test_unavailable_helper_and_unknown_helper_building(session):
    add_helper(session, 2, "Z", helper_status="busy")
    request = add_request(session)
    assert evaluate_candidates(session, request, NOW).issue == "no_available_helper"
    session.get(User, 2).availability_status = "available"
    session.get(User, 2).campus_building = "Not a building"
    session.flush()
    assert evaluate_candidates(session, request, NOW).issue == "no_available_helper"


def test_handoff_buffer_is_hard_deadline_boundary(session):
    add_helper(session, 2, "Z")
    at_boundary = add_request(session, minutes=HANDOFF_BUFFER_MINUTES)
    just_short = add_request(session, minutes=HANDOFF_BUFFER_MINUTES - 1)
    assert len(evaluate_candidates(session, at_boundary, NOW).candidates) == 1
    assert evaluate_candidates(session, just_short, NOW).issue == "unreachable_before_deadline"


def test_alternative_requires_uncontacted_timely_candidate(session):
    helper, item = add_helper(session, 2, "A")
    request = add_request(session, brand="Casio", policy="ask_before_substitute", minutes=5)
    assert evaluate_candidates(session, request, NOW).issue == "unreachable_before_deadline"
    helper.campus_building = "Z"
    session.flush()
    assert evaluate_candidates(session, request, NOW).issue == "alternatives_available_needs_confirmation"
    contact(session, request, helper, item)
    assert evaluate_candidates(session, request, NOW).issue == "candidate_exhausted"


def test_exact_only_never_selects_generic_and_distinguishes_late_exact(session):
    add_helper(session, 2, "Z")
    request = add_request(session, brand="Casio", policy="exact_only", minutes=10)
    assert evaluate_candidates(session, request, NOW).issue == "exact_preference_unavailable"
    add_helper(session, 3, "A", brand="Casio")
    assert evaluate_candidates(session, request, NOW).issue == "exact_preference_unavailable"


def test_contacted_exact_can_prompt_for_feasible_substitute(session):
    exact, exact_item = add_helper(session, 2, "Z", brand="Casio")
    add_helper(session, 3, "Y")
    request = add_request(session, brand="Casio", policy="ask_before_substitute")
    assert evaluate_candidates(session, request, NOW).candidates[0][0].id == exact.id
    contact(session, request, exact, exact_item)
    assert evaluate_candidates(session, request, NOW).issue == "alternatives_available_needs_confirmation"
    request.substitution_policy = "equivalent_ok"
    session.flush()
    assert [helper.id for helper, _, _ in evaluate_candidates(session, request, NOW).candidates] == [3]


def test_legacy_sqlite_migration_is_repeatable_and_preserves_rows(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    old_tables = (
        "CREATE TABLE help_requests (id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL, "
        "category VARCHAR(32) NOT NULL, raw_text TEXT, item_type VARCHAR(64) NOT NULL, "
        "location VARCHAR(80) NOT NULL, deadline DATETIME NOT NULL, urgency VARCHAR(32), "
        "status VARCHAR(32) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)",
        "CREATE TABLE help_request_drafts (id INTEGER PRIMARY KEY, requester_id INTEGER NOT NULL, "
        "raw_text TEXT NOT NULL, item_type VARCHAR(64), location VARCHAR(80), deadline DATETIME, "
        "urgency VARCHAR(32), missing_fields_json TEXT NOT NULL, public_question VARCHAR(300), "
        "public_turns_json TEXT NOT NULL, status VARCHAR(32) NOT NULL, request_id INTEGER, "
        "created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)",
        "CREATE TABLE user_items (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
        "item_type VARCHAR(64) NOT NULL, item_name VARCHAR(120) NOT NULL, available BOOLEAN NOT NULL)",
        "CREATE TABLE help_offers (id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, "
        "helper_id INTEGER NOT NULL, item_id INTEGER NOT NULL, status VARCHAR(32) NOT NULL, "
        "sent_at DATETIME NOT NULL, responded_at DATETIME, expires_at DATETIME NOT NULL, "
        "requester_confirmed_at DATETIME, helper_confirmed_at DATETIME, "
        "UNIQUE(request_id, helper_id))",
        "CREATE TABLE agent_events (id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, "
        "event_type VARCHAR(64) NOT NULL, public_message VARCHAR(300) NOT NULL, "
        "metadata_json TEXT NOT NULL, dedupe_key VARCHAR(120) NOT NULL UNIQUE, "
        "created_at DATETIME NOT NULL)",
    )
    with engine.begin() as connection:
        for statement in old_tables:
            connection.exec_driver_sql(statement)
        connection.exec_driver_sql(
            "INSERT INTO help_requests VALUES (8,1,'borrow','old Casio wording',"
            "'scientific_calculator','VA','2026-11-11 12:00:00',NULL,'failed',"
            "'2026-11-10 12:00:00','2026-11-10 12:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO help_request_drafts VALUES (9,1,'old text','scientific_calculator',"
            "'Z',NULL,NULL,'[]',NULL,'[]','collecting_details',NULL,"
            "'2026-11-10 12:00:00','2026-11-10 12:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO user_items VALUES (10,2,'scientific_calculator','old item',1)"
        )
        connection.exec_driver_sql(
            "INSERT INTO help_offers VALUES (11,8,2,10,'declined',"
            "'2026-11-10 12:00:00',NULL,'2026-11-10 12:05:00',NULL,NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO agent_events VALUES (12,8,'offer_declined','Old public event',"
            "'{}','8:old:12','2026-11-10 12:01:00')"
        )

    initialize_database(engine)
    initialize_database(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT status, raw_text, category, need_summary, urgency, "
                                       "substitution_policy, matching_issue "
                                       "FROM help_requests WHERE id=8")).one() == (
            "failed", "old Casio wording", "borrow", "科学计算器", "normal",
            "equivalent_ok", None
        )
        assert connection.execute(text("SELECT category, need_summary, substitution_policy "
                                       "FROM help_request_drafts WHERE id=9")).one() == (
            "borrow", "科学计算器", "equivalent_ok"
        )
        assert connection.execute(text("SELECT brand, model FROM user_items WHERE id=10")).one() == (None, None)
        assert connection.execute(text("SELECT status, message, response_type, capability_confirmed_at "
                                       "FROM help_offers WHERE id=11")).one() == (
            "declined", None, "direct", None
        )
        assert connection.execute(text("SELECT public_message, dedupe_key FROM agent_events WHERE id=12")).one() == (
            "Old public event", "8:old:12"
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO agent_events VALUES (13,8,'offer_declined','duplicate',"
                "'{}','8:old:12','2026-11-10 12:02:00')"
            )
        for table, column in (("help_requests", "preferred_brand"),
                              ("help_request_drafts", "preferred_model"),
                              ("user_items", "brand"), ("help_offers", "message")):
            assert [item["name"] for item in inspect(connection).get_columns(table)].count(column) == 1
        offer_item_column = next(item for item in inspect(connection).get_columns("help_offers")
                                 if item["name"] == "item_id")
        assert offer_item_column["nullable"] is True
    engine.dispose()
