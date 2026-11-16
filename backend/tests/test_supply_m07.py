"""M07 supply-first profile, search, invitation, and privacy contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.database import initialize_database, make_engine
from app.models import (
    DailyAvailability,
    DailyAvailableItem,
    DailyAvailableService,
    HelpOffer,
    HelpRequest,
    UserItem,
)
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.seed import seed_demo_people
from app.services import ClaimConflict
from app.supply_matching import search_supply_candidates
from app.supply_services import accept_invitation


HK = timezone(timedelta(hours=8))


def _app(tmp_path):
    return create_app(
        f"sqlite:///{(tmp_path / 'supply-m07.db').as_posix()}",
        ProviderRouter(MockLLMProvider()),
    )


def _headers(helper_id):
    return {"X-Demo-User-Id": str(helper_id)}


def _profile_item_input(item):
    return {
        key: item[key]
        for key in ("id", "item_type", "item_name", "brand", "model", "active")
        if key in item
    }


def _today_window():
    local = datetime.now(HK)
    start = max(local.replace(hour=0, minute=0, second=0, microsecond=0), local - timedelta(minutes=5))
    end = local.replace(hour=23, minute=59, second=0, microsecond=0)
    return start.isoformat(), end.isoformat()


def _prepare_helper(client, helper_id, *, model, building, service=True):
    profile = client.get(
        f"/api/demo/users/{helper_id}/helper-profile", headers=_headers(helper_id),
    ).json()
    item = profile["items"][0]
    item.update({
        "item_name": f"Calculator {helper_id}",
        "brand": "Casio" if model else None,
        "model": model,
        "active": True,
    })
    services = [{"service_code": "moving", "service_name": "搬运实验器材", "active": True}] if service else []
    saved = client.put(
        f"/api/demo/users/{helper_id}/helper-profile",
        headers=_headers(helper_id),
        json={"items": [_profile_item_input(item)], "services": services},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    start, end = _today_window()
    daily = client.put(
        f"/api/demo/users/{helper_id}/daily-availability",
        headers=_headers(helper_id),
        json={
            "willing": True,
            "available_from": start,
            "available_until": end,
            "campus_building": building,
            "accepts_urgent": True,
            "item_ids": [body["items"][0]["id"]],
            "service_ids": [entry["id"] for entry in body["services"]],
        },
    )
    assert daily.status_code == 200, daily.text
    return body


def _borrow_request(client, **overrides):
    payload = {
        "category": "borrow",
        "need_summary": "Casio fx-991CN X 科学计算器",
        "item_type": "scientific_calculator",
        "preferred_brand": "Casio",
        "preferred_model": "fx-991CN X",
        "substitution_policy": "ask_before_substitute",
        "location": "Z",
        "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        "urgency": "high",
    }
    payload.update(overrides)
    response = client.post("/api/requests", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_profile_and_daily_status_are_private_and_today_scoped(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        profile = _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        assert profile["services"][0]["service_code"] == "moving"
        daily = client.get("/api/demo/users/5/daily-availability", headers=_headers(5))
        assert daily.status_code == 200
        assert daily.json()["availability"]["campus_building"] == "Z"
        assert client.get("/api/demo/users/5/helper-profile", headers=_headers(7)).status_code == 403
        assert client.get("/api/demo/users/5/daily-availability", headers=_headers(7)).status_code == 403


def test_search_invite_and_first_accept_use_targeted_flow_not_public_board(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        _prepare_helper(client, 7, model=None, building="Y")
        request = _borrow_request(client)

        search = client.post("/api/helpers/search", json={"request_id": request["id"], "limit": 5})
        assert search.status_code == 200, search.text
        candidates = search.json()["candidates"]
        assert candidates[0]["helper_id"] == 5
        assert candidates[0]["match_reason"] == "exact_model"
        assert candidates[0]["item_name"] == "Calculator 5"
        assert candidates[0]["item_brand"] == "Casio"
        assert candidates[0]["item_model"] == "fx-991CN X"
        assert candidates[1]["helper_id"] == 7
        assert candidates[1]["item_name"] == "Calculator 7"
        serialized = search.text
        for private_key in ("campus_building", "reliability_score", "inventory", "item_id"):
            assert private_key not in serialized

        created = client.post(
            f"/api/requests/{request['id']}/invitations",
            json={"helper_ids": [5, 7]},
        )
        assert created.status_code == 200, created.text
        assert created.json()["request_status"] == "awaiting_response"
        assert len(created.json()["batches"][0]["invitations"]) == 2
        board = client.get("/api/helper-board", headers=_headers(5)).json()
        assert all(entry["id"] != request["id"] for entry in board["requests"])

        inbox = client.get("/api/helpers/5/invitations", headers=_headers(5)).json()
        invitation_id = inbox["pending"][0]["id"]
        accepted = client.post(f"/api/invitations/{invitation_id}/accept", headers=_headers(5))
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"
        assert client.get(f"/api/requests/{request['id']}").json()["matched_helper"] == "Erin"
        losing = client.get("/api/helpers/7/invitations", headers=_headers(7)).json()
        assert losing["pending"] == []
        assert losing["history"][0]["status"] == "cancelled"


def test_requester_can_close_and_reopen_invitation_round_on_same_request(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        request = _borrow_request(client)
        assert client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
        ).status_code == 200
        closed = client.post(f"/api/requests/{request['id']}/invitations/close")
        assert closed.status_code == 200
        assert closed.json()["request_status"] == "searching"
        search = client.post("/api/helpers/search", json={"request_id": request["id"], "limit": 5})
        assert search.json()["candidates"][0]["helper_id"] == 5
        reopened = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
        )
        assert reopened.status_code == 200, reopened.text
        assert [batch["round_number"] for batch in reopened.json()["batches"]] == [1, 2]


def test_service_search_uses_controlled_capability_and_decline_excludes_helper(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        created = client.post("/api/requests", json={
            "category": "service",
            "need_summary": "搬运实验器材",
            "item_type": "other",
            "service_code": "moving",
            "service_name": "搬运实验器材",
            "location": "Z",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "urgency": "normal",
        })
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        search = client.post("/api/helpers/search", json={"request_id": request_id, "limit": 5}).json()
        assert search["candidates"][0]["match_reason"] == "service_exact"
        client.post(f"/api/requests/{request_id}/invitations", json={"helper_ids": [5]})
        invitation_id = client.get("/api/helpers/5/invitations", headers=_headers(5)).json()["pending"][0]["id"]
        declined = client.post(
            f"/api/invitations/{invitation_id}/decline",
            headers=_headers(5),
            json={"reason": "cannot_arrive"},
        )
        assert declined.status_code == 200
        client.post(f"/api/requests/{request_id}/invitations/close")
        repeated = client.post("/api/helpers/search", json={"request_id": request_id, "limit": 5}).json()
        assert repeated["candidates"] == []


def test_two_targeted_helpers_accept_concurrently_but_only_one_offer_wins(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        _prepare_helper(client, 7, model=None, building="Y")
        request = _borrow_request(client)
        created = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5, 7]},
        ).json()
        invitations = created["batches"][0]["invitations"]
        gate = Barrier(2)

        def attempt(invitation):
            with app.state.session_factory() as session:
                gate.wait()
                try:
                    offer = accept_invitation(session, invitation["id"], invitation["helper_id"])
                    return ("accepted", offer.id)
                except ClaimConflict:
                    return ("conflict", None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, invitations))
        assert sorted(result[0] for result in results) == ["accepted", "conflict"]
        with app.state.session_factory() as session:
            accepted = session.scalars(select(HelpOffer).where(
                HelpOffer.request_id == request["id"], HelpOffer.status == "accepted",
            )).all()
            assert len(accepted) == 1


def test_invitation_websocket_is_private_invalidation_only(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        request = _borrow_request(client)
        origin = {"origin": "http://127.0.0.1:5173"}
        with client.websocket_connect("/ws/helpers/5/invitations?demo_user_id=5", headers=origin) as socket:
            created = client.post(
                f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
            )
            assert created.status_code == 200
            assert client.portal is not None
            client.portal.call(app.state.event_scanner.scan_once)
            frame = socket.receive_json()
        assert frame["resource_kind"] == "invitation"
        assert frame["resource_id"] == 5
        assert frame["event_type"] == "invitations_changed"
        serialized = str(frame)
        for private_key in ("campus_building", "candidate_item_id", "reliability_score", "inventory"):
            assert private_key not in serialized
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/ws/helpers/5/invitations?demo_user_id=7", headers=origin):
                pass
        assert denied.value.code == 1008


def test_reachability_uses_arrival_against_deadline_and_available_until_with_fixed_clock(tmp_path):
    app = _app(tmp_path)
    fixed_now = datetime(2026, 11, 16, 4, 0, tzinfo=timezone.utc)

    def naive(value):
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    with TestClient(app):
        with app.state.session_factory() as session:
            seed_demo_people(session)
            item = session.scalar(select(UserItem).where(UserItem.user_id == 5).order_by(UserItem.id))
            item.item_type = "scientific_calculator"
            item.brand = "Casio"
            item.model = "fx-991CN X"
            item.is_active = True
            item.available = True
            daily = DailyAvailability(
                user_id=5,
                local_date=fixed_now.astimezone(HK).date(),
                willing=True,
                available_from=naive(fixed_now - timedelta(minutes=5)),
                available_until=naive(fixed_now + timedelta(minutes=10)),
                campus_building="Z",
                accepts_urgent=True,
            )
            request = HelpRequest(
                requester_id=1,
                category="borrow",
                need_summary="Casio calculator",
                item_type="scientific_calculator",
                preferred_brand="Casio",
                preferred_model="fx-991CN X",
                substitution_policy="ask_before_substitute",
                location="Z",
                deadline=naive(fixed_now + timedelta(minutes=30)),
                urgency="high",
                status="draft",
            )
            session.add_all([daily, request])
            session.flush()
            session.add(DailyAvailableItem(daily_availability_id=daily.id, item_id=item.id))
            session.flush()

            # Handoff arrival is 12:03 HKT. Availability may end before the
            # 12:30 deadline as long as arrival is no later than both bounds.
            result = search_supply_candidates(session, request, fixed_now)
            assert [candidate.helper.id for candidate in result.candidates] == [5]
            daily.available_until = naive(fixed_now + timedelta(minutes=3))
            request.deadline = naive(fixed_now + timedelta(minutes=3))
            session.flush()
            assert [candidate.helper.id for candidate in search_supply_candidates(
                session, request, fixed_now,
            ).candidates] == [5]

            daily.available_until = naive(fixed_now + timedelta(minutes=3, seconds=-1))
            session.flush()
            too_late = search_supply_candidates(session, request, fixed_now)
            assert too_late.candidates == []
            assert too_late.issue == "unreachable_before_deadline"


def test_yesterday_suggestions_exclude_foreign_and_soft_deactivated_capabilities(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        helper_profile = _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        foreign_profile = _prepare_helper(client, 7, model="fx-82MS", building="Y")
        own_item_id = helper_profile["items"][0]["id"]
        own_service_id = helper_profile["services"][0]["id"]
        foreign_item_id = foreign_profile["items"][0]["id"]
        foreign_service_id = foreign_profile["services"][0]["id"]

        with app.state.session_factory() as session:
            previous = session.scalar(select(DailyAvailability).where(DailyAvailability.user_id == 5))
            previous.local_date -= timedelta(days=1)
            session.add(DailyAvailableItem(
                daily_availability_id=previous.id,
                item_id=foreign_item_id,
            ))
            session.add(DailyAvailableService(
                daily_availability_id=previous.id,
                service_id=foreign_service_id,
            ))
            session.commit()

        saved = client.put(
            "/api/demo/users/5/helper-profile",
            headers=_headers(5),
            json={
                "items": [_profile_item_input(item) for item in helper_profile["items"]],
                "services": [],
            },
        )
        assert saved.status_code == 200, saved.text
        suggestions = client.get(
            "/api/demo/users/5/daily-availability", headers=_headers(5),
        ).json()
        assert suggestions["availability"] is None
        assert suggestions["suggested_item_ids"] == [own_item_id]
        assert suggestions["suggested_service_ids"] == []
        assert foreign_item_id not in suggestions["suggested_item_ids"]
        assert own_service_id not in suggestions["suggested_service_ids"]


def test_substitute_proposal_full_flow_uses_only_today_selected_item(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        profile = _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        updated = client.put(
            "/api/demo/users/5/helper-profile",
            headers=_headers(5),
            json={
                "items": [
                    *[_profile_item_input(item) for item in profile["items"]],
                    {
                        "item_type": "scientific_calculator",
                        "item_name": "Canon F-789",
                        "brand": "Canon",
                        "model": "F-789",
                        "active": True,
                    },
                ],
                "services": profile["services"],
            },
        )
        assert updated.status_code == 200, updated.text
        items = updated.json()["items"]
        substitute = next(item for item in items if item["item_name"] == "Canon F-789")
        daily = client.get(
            "/api/demo/users/5/daily-availability", headers=_headers(5),
        ).json()["availability"]
        daily["item_ids"] = [item["id"] for item in items]
        assert client.put(
            "/api/demo/users/5/daily-availability", headers=_headers(5), json=daily,
        ).status_code == 200

        request = _borrow_request(client)
        created = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
        )
        invitation_id = created.json()["batches"][0]["invitations"][0]["id"]
        proposal = client.post(
            f"/api/invitations/{invitation_id}/propose-substitute",
            headers=_headers(5),
            json={"item_id": substitute["id"], "note": "同类科学计算器"},
        )
        assert proposal.status_code == 200, proposal.text
        assert proposal.json()["status"] == "proposed"
        assert proposal.json()["item_name"] == "Canon F-789"

        requester_view = client.get(f"/api/requests/{request['id']}/invitations").json()
        shown = requester_view["batches"][0]["invitations"][0]
        assert shown["item_name"] == "Canon F-789"
        accepted = client.post(f"/api/invitations/{invitation_id}/accept-substitute")
        assert accepted.status_code == 200, accepted.text
        with app.state.session_factory() as session:
            offer = session.scalar(select(HelpOffer).where(HelpOffer.invitation_id == invitation_id))
            assert offer.item_id == substitute["id"]
            assert session.get(UserItem, substitute["id"]).available is False


def test_completed_handoff_keeps_item_unavailable_for_new_search(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        profile = _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        item_id = profile["items"][0]["id"]
        first = _borrow_request(client)
        created = client.post(
            f"/api/requests/{first['id']}/invitations", json={"helper_ids": [5]},
        ).json()
        invitation_id = created["batches"][0]["invitations"][0]["id"]
        offer = client.post(
            f"/api/invitations/{invitation_id}/accept", headers=_headers(5),
        ).json()
        assert client.post(f"/api/requests/{first['id']}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{first['id']}/complete").json()["status"] == "in_progress"
        completed = client.post(
            f"/api/offers/{offer['id']}/confirm-completion", headers=_headers(5),
        )
        assert completed.json()["request_status"] == "completed"
        with app.state.session_factory() as session:
            assert session.get(UserItem, item_id).available is False

        second = _borrow_request(client)
        search = client.post(
            "/api/helpers/search", json={"request_id": second["id"], "limit": 5},
        )
        assert search.status_code == 200
        assert all(candidate["helper_id"] != 5 for candidate in search.json()["candidates"])


def test_m07_conflicts_return_stable_codes(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        profile = _prepare_helper(client, 5, model="fx-991CN X", building="Z")
        _prepare_helper(client, 7, model=None, building="Y")
        updated = client.put(
            "/api/demo/users/5/helper-profile",
            headers=_headers(5),
            json={
                "items": [
                    *[_profile_item_input(item) for item in profile["items"]],
                    {
                        "item_type": "scientific_calculator",
                        "item_name": "Canon F-789",
                        "brand": "Canon",
                        "model": "F-789",
                        "active": True,
                    },
                ],
                "services": profile["services"],
            },
        ).json()
        substitute_id = next(
            item["id"] for item in updated["items"] if item["item_name"] == "Canon F-789"
        )
        daily = client.get(
            "/api/demo/users/5/daily-availability", headers=_headers(5),
        ).json()["availability"]
        daily["item_ids"] = [item["id"] for item in updated["items"]]
        client.put("/api/demo/users/5/daily-availability", headers=_headers(5), json=daily)

        request = _borrow_request(client)
        no_round = client.post(f"/api/requests/{request['id']}/invitations/close")
        assert (no_round.status_code, no_round.json()["code"]) == (409, "no_open_round")
        stale = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [999]},
        )
        assert (stale.status_code, stale.json()["code"]) == (409, "candidates_stale")
        opened = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
        ).json()
        invitation_id = opened["batches"][0]["invitations"][0]["id"]
        duplicate_round = client.post(
            f"/api/requests/{request['id']}/invitations", json={"helper_ids": [5]},
        )
        assert (duplicate_round.status_code, duplicate_round.json()["code"]) == (
            409, "invitation_round_open",
        )
        not_searchable = client.post(
            "/api/helpers/search", json={"request_id": request["id"], "limit": 5},
        )
        assert (not_searchable.status_code, not_searchable.json()["code"]) == (
            409, "request_not_searchable",
        )
        client.post(
            f"/api/invitations/{invitation_id}/decline",
            headers=_headers(5), json={"reason": "declined"},
        )
        inactive = client.post(
            f"/api/invitations/{invitation_id}/accept", headers=_headers(5),
        )
        assert (inactive.status_code, inactive.json()["code"]) == (409, "invitation_inactive")
        client.post(f"/api/requests/{request['id']}/invitations/close")

        exact = _borrow_request(client, substitution_policy="exact_only")
        exact_invitation = client.post(
            f"/api/requests/{exact['id']}/invitations", json={"helper_ids": [5]},
        ).json()["batches"][0]["invitations"][0]["id"]
        substitute_denied = client.post(
            f"/api/invitations/{exact_invitation}/propose-substitute",
            headers=_headers(5), json={"item_id": substitute_id},
        )
        assert (substitute_denied.status_code, substitute_denied.json()["code"]) == (
            409, "substitute_not_allowed",
        )

        race = _borrow_request(client)
        invitations = client.post(
            f"/api/requests/{race['id']}/invitations", json={"helper_ids": [5, 7]},
        ).json()["batches"][0]["invitations"]
        first, second = invitations
        assert client.post(
            f"/api/invitations/{first['id']}/accept", headers=_headers(first["helper_id"]),
        ).status_code == 200
        claimed = client.post(
            f"/api/invitations/{second['id']}/accept", headers=_headers(second["helper_id"]),
        )
        assert (claimed.status_code, claimed.json()["code"]) == (409, "already_claimed")


def test_m07_legacy_sqlite_initialization_is_repeatable(tmp_path):
    path = tmp_path / "legacy-m07.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE user_items (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, "
            "item_type VARCHAR(64) NOT NULL, item_name VARCHAR(120) NOT NULL, "
            "available BOOLEAN NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE help_offers (id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, "
            "helper_id INTEGER NOT NULL, item_id INTEGER NOT NULL, status VARCHAR(32) NOT NULL, "
            "sent_at DATETIME NOT NULL, responded_at DATETIME, expires_at DATETIME NOT NULL, "
            "requester_confirmed_at DATETIME, helper_confirmed_at DATETIME)"
        )
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    initialize_database(engine)
    initialize_database(engine)
    schema = inspect(engine)
    assert {
        "user_service_capabilities",
        "daily_availability",
        "daily_available_items",
        "daily_available_services",
        "invitation_batches",
        "help_invitations",
    }.issubset(schema.get_table_names())
    assert {"invitation_id", "service_capability_id"}.issubset(
        {column["name"] for column in schema.get_columns("help_offers")}
    )
    assert "is_active" in {column["name"] for column in schema.get_columns("user_items")}
    assert "uq_open_invitation_batch" in {
        index["name"] for index in schema.get_indexes("invitation_batches")
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM users WHERE id = 1")).scalar_one() == 1
    engine.dispose()
