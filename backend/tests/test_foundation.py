"""Acceptance checks for Milestone 01."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import HelpRequest, User


def payload(**overrides):
    data = {
        "item_type": "scientific_calculator",
        "location": " VA ",
        "deadline": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "raw_text": "Exam in VA",
    }
    data.update(overrides)
    return data


def test_create_get_and_restart_persist(tmp_path):
    db_file = tmp_path / "requests.db"
    url = f"sqlite:///{db_file.as_posix()}"
    with TestClient(create_app(url)) as client:
        assert client.get("/api/system/health").json() == {"status": "ok"}
        created = client.post("/api/requests", json=payload())
        assert created.status_code == 201
        body = created.json()
        assert body["requester_id"] == 1
        assert body["category"] == "borrow"
        assert body["status"] == "draft"
        assert body["location"] == "VA"
        assert body["deadline"].endswith("Z")
        assert client.get(f"/api/requests/{body['id']}").json() == body

    with TestClient(create_app(url)) as client:
        assert client.get(f"/api/requests/{body['id']}").json() == body
        assert client.get("/api/requests/999999").status_code == 404

    engine = create_engine(url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        assert session.scalar(select(func.count()).select_from(HelpRequest)) == 1
    engine.dispose()


def test_reject_invalid_requests_without_writing(tmp_path):
    url = f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}"
    with TestClient(create_app(url)) as client:
        invalid = [
            payload(location="  "),
            payload(deadline=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()),
            payload(deadline="2026-11-04T10:00:00"),
            payload(item_type="unknown_item"),
            payload(status="matched"),
            payload(requester_id=999),
            payload(category="help"),
        ]
        for value in invalid:
            assert client.post("/api/requests", json=value).status_code == 422

    engine = create_engine(url)
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(HelpRequest)) == 0
    engine.dispose()
