"""M07 supply-first profile, search, invitation, and privacy contracts."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.models import HelpOffer
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.seed import seed_demo_people
from app.services import ClaimConflict
from app.supply_services import accept_invitation


HK = timezone(timedelta(hours=8))


def _app(tmp_path):
    return create_app(
        f"sqlite:///{(tmp_path / 'supply-m07.db').as_posix()}",
        ProviderRouter(MockLLMProvider()),
    )


def _headers(helper_id):
    return {"X-Demo-User-Id": str(helper_id)}


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
        json={"items": [item], "services": services},
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


def _borrow_request(client):
    response = client.post("/api/requests", json={
        "category": "borrow",
        "need_summary": "Casio fx-991CN X 科学计算器",
        "item_type": "scientific_calculator",
        "preferred_brand": "Casio",
        "preferred_model": "fx-991CN X",
        "substitution_policy": "ask_before_substitute",
        "location": "Z",
        "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        "urgency": "high",
    })
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
        assert candidates[1]["helper_id"] == 7
        serialized = search.text
        for private_key in ("campus_building", "reliability_score", "inventory", "item_name"):
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
