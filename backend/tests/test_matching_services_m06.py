"""Requester-visible M06 recovery and authorization behavior with offline Mock."""

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import create_app
from app.models import HelpOffer
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider
from app.seed import seed_demo_people


def _app(tmp_path):
    return create_app(f"sqlite:///{(tmp_path / 'matching-m06.db').as_posix()}", ProviderRouter(MockLLMProvider()))


def _request(client, item_type="scientific_calculator", location="Z", minutes=30, **preferences):
    response = client.post("/api/requests", json={
        "category": "borrow", "need_summary": "校园物品求助",
        "item_type": item_type, "location": location, "urgency": "normal",
        "deadline": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
        **preferences,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _claim(client, request_id, helper_id, **values):
    payload = {"capability_confirmed": True, "response_type": "direct", **values}
    return client.post(f"/api/requests/{request_id}/claim",
                       headers={"X-Demo-User-Id": str(helper_id)}, json=payload)


def _offer_count(app, request_id):
    with app.state.session_factory() as session:
        return session.scalar(select(func.count()).select_from(HelpOffer).where(HelpOffer.request_id == request_id))


def test_original_casio_z_sentence_completes_with_mock(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = _request(client, preferred_brand="Casio", need_summary="Casio 科学计算器")
        result = client.post(f"/api/requests/{request['id']}/publish")
        assert result.status_code == 200 and result.json()["status"] == "awaiting_response"
        assert _offer_count(app, request["id"]) == 0
        for helper_id in (5, 7):
            board = client.get("/api/helper-board", headers={"X-Demo-User-Id": str(helper_id)}).json()
            assert board["requests"][0]["need_summary"] == "Casio 科学计算器"
        claimed = _claim(client, request["id"], 5, offered_brand="Casio", help_note="可在十分钟后到达")
        assert claimed.status_code == 200 and claimed.json()["status"] == "accepted"
        offer_id = claimed.json()["id"]
        assert _claim(client, request["id"], 7, offered_brand="Casio").status_code == 409
        matched = client.get(f"/api/requests/{request['id']}").json()
        assert matched["status"] == "matched" and matched["matched_helper"] == "Erin"
        assert matched["helper_note"] == "可在十分钟后到达"
        assert client.post(f"/api/requests/{request['id']}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/requests/{request['id']}/complete").json()["status"] == "in_progress"
        finished = client.post(f"/api/offers/{offer_id}/confirm-completion", headers={"X-Demo-User-Id": "5"})
        assert finished.json()["request_status"] == "completed"


def test_substitution_proposal_requires_requester_consent(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = _request(client, preferred_brand="Casio")
        request_id = request["id"]
        assert client.post(f"/api/requests/{request_id}/publish").json()["status"] == "awaiting_response"
        proposal = _claim(client, request_id, 6, response_type="direct",
                          offered_brand="Canon", offered_model="F-789", help_note="可提供同类型号")
        assert proposal.status_code == 200, proposal.text
        assert proposal.json()["status"] == "proposed"
        assert proposal.json()["response_type"] == "substitute"
        waiting = client.get(f"/api/requests/{request_id}").json()
        assert waiting["status"] == "awaiting_response"
        assert waiting["proposals"][0]["help_note"] == "可提供同类型号"
        assert client.post(f"/api/offers/{proposal.json()['id']}/accept-proposal",
                           headers={"X-Demo-User-Id": "2"}).status_code == 403
        accepted = client.post(f"/api/offers/{proposal.json()['id']}/accept-proposal")
        assert accepted.status_code == 200 and accepted.json()["status"] == "matched"
        matched = accepted.json()
        assert matched["proposals"] == []
        assert matched["offered_brand"] == "Canon" and matched["response_type"] == "substitute"


def test_service_request_ignores_inventory_location_and_availability(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        created = client.post("/api/requests", json={
            "category": "service",
            "need_summary": "有偿帮忙搬运实验器材",
            "item_type": "other",
            "location": "G",
            "urgency": "high",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
        })
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        assert client.post(f"/api/requests/{request_id}/publish").json()["status"] == "awaiting_response"

        # Kai is seeded as unavailable, far from G, and owns only an adapter.
        board = client.get("/api/helper-board", headers={"X-Demo-User-Id": "11"})
        assert board.status_code == 200
        entry = next(item for item in board.json()["requests"] if item["id"] == request_id)
        assert entry["category"] == "service"
        assert entry["need_summary"] == "有偿帮忙搬运实验器材"
        assert entry["urgency"] == "high"

        claimed = _claim(client, request_id, 11, help_note="我可以在截止前搬完")
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["status"] == "accepted"
        assert claimed.json()["item_type"] is None
        assert claimed.json()["offered_brand"] is None
        offer_id = claimed.json()["id"]
        assert client.post(f"/api/requests/{request_id}/start").json()["status"] == "in_progress"
        assert client.post(f"/api/offers/{offer_id}/confirm-completion",
                           headers={"X-Demo-User-Id": "11"}).json()["request_status"] == "in_progress"
        completed = client.post(f"/api/requests/{request_id}/complete")
        assert completed.json()["status"] == "completed"
        assert completed.json()["helper_note"] == "我可以在截止前搬完"


def test_exact_only_rejects_mismatch_but_accepts_normalized_match(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        exact = _request(client, preferred_brand="Casio", preferred_model="fx-991cnx",
                         substitution_policy="exact_only")
        assert client.post(f"/api/requests/{exact['id']}/publish").json()["status"] == "awaiting_response"
        mismatch = _claim(client, exact["id"], 6, offered_brand="Canon", offered_model="F-789")
        assert mismatch.status_code == 409
        assert _offer_count(app, exact["id"]) == 0
        match = _claim(client, exact["id"], 6, offered_brand="ＣＡＳＩＯ", offered_model="FX 991CNX")
        assert match.status_code == 200 and match.json()["status"] == "accepted"


def test_deadline_and_location_correction_are_requester_only(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        bad = client.post("/api/requests", json={
            "item_type": "umbrella", "location": "火星楼",
            "deadline": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
        })
        assert bad.status_code == 422 and bad.json()["code"] == "unknown_location"
        assert client.get("/api/locations").json()[0].keys() == {"code", "label_zh", "label_en"}

        request = _request(client, item_type="umbrella", minutes=4)
        new_deadline = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        assert client.patch(f"/api/requests/{request['id']}", json={"deadline": new_deadline},
                            headers={"X-Demo-User-Id": "2"}).status_code == 403
        updated = client.patch(f"/api/requests/{request['id']}", json={"deadline": new_deadline, "location": "Z座"})
        assert updated.status_code == 200 and updated.json()["location"] == "Z"
        assert updated.json()["matching_issue"] is None
        assert client.post(f"/api/requests/{request['id']}/search").json()["status"] == "awaiting_response"
        assert client.patch(f"/api/requests/{request['id']}", json={"location": "L"}).status_code == 409


def test_requester_response_does_not_serialize_private_candidate_data(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = _request(client, preferred_brand="Casio")
        result = client.post(f"/api/requests/{request['id']}/search")
        body = result.json()
        assert body["status"] == "awaiting_response"
        for private_key in ("candidate_count", "campus_building", "reliability_score", "item_name", "inventory", "available", "walk_minutes"):
            assert private_key not in result.text
        assert body["matched_helper"] is None  # Identity appears only after acceptance.


def test_helper_can_accept_multiple_requests_without_inventory_reservation(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        first = _request(client, preferred_brand="Casio")
        second = _request(client, preferred_brand="Casio")
        assert client.post(f"/api/requests/{first['id']}/search").json()["status"] == "awaiting_response"
        assert client.post(f"/api/requests/{second['id']}/search").json()["status"] == "awaiting_response"
        assert client.get("/api/helpers/5/offers", headers={"X-Demo-User-Id": "5"}).json() == []
        assert _claim(client, first["id"], 5, offered_brand="Casio").status_code == 200
        second_claim = _claim(client, second["id"], 5, offered_brand="Casio")
        assert second_claim.status_code == 200
        assert _offer_count(app, first["id"]) == 1 and _offer_count(app, second["id"]) == 1


def test_agent_timeline_and_websocket_frames_exclude_private_matching_data(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        with app.state.session_factory() as session:
            seed_demo_people(session)
        request = _request(client, preferred_brand="Casio")
        request_id = request["id"]
        origin = {"origin": "http://127.0.0.1:5173"}
        with client.websocket_connect(f"/ws/requests/{request_id}?demo_user_id=1", headers=origin) as requester_ws, \
             client.websocket_connect("/ws/helper-board?demo_user_id=5", headers=origin) as helper_ws:
            agent = client.post(f"/api/agent/requests/{request_id}/search")
            assert agent.status_code == 200
            assert client.portal is not None
            client.portal.call(app.state.event_scanner.scan_once)
            request_frames = [requester_ws.receive_json()]
            helper_frames = [helper_ws.receive_json()]
            assert helper_frames[0]["event_type"] == "board_changed"
        view = client.get(f"/api/requests/{request_id}").json()
        serialized = json.dumps({"agent": agent.json(), "timeline": view["events"],
                                 "request_ws": request_frames, "helper_ws": helper_frames}, ensure_ascii=False)
        for private_key in ("candidate_count", "item_name", "campus_building", "reliability_score",
                            "inventory", "walk_minutes", "helper_location", "item_id"):
            assert private_key not in serialized
        for uncontacted_name in ("Bob", "Carol", "Felix", "Grace", "Hana"):
            assert uncontacted_name not in serialized
