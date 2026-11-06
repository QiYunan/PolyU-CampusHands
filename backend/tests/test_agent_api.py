from fastapi.testclient import TestClient
import sqlite3
from sqlalchemy import inspect

from app.main import create_app
from app.database import initialize_database, make_engine
from app.providers.fallback import ProviderRouter
from app.providers.mock import MockLLMProvider


def test_status_does_not_expose_secrets_and_old_db_migrates(tmp_path):
    path = (tmp_path / "old.db").as_posix()
    app = create_app(f"sqlite:///{path}", ProviderRouter(MockLLMProvider()))
    with TestClient(app) as client:
        status = client.get("/api/system/llm-status")
        assert status.status_code == 200
        assert status.json()["primary"] == "mock"
        assert "api_key" not in status.text.lower()
        assert client.get("/api/system/health").status_code == 200
    app2 = create_app(f"sqlite:///{path}", ProviderRouter(MockLLMProvider()))
    with TestClient(app2) as client:
        assert client.get("/api/system/health").status_code == 200


def test_existing_offer_table_gets_message_column_without_rebuild(tmp_path):
    path = tmp_path / "legacy-offers.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE help_offers (id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, helper_id INTEGER NOT NULL, item_id INTEGER NOT NULL, status VARCHAR(32) NOT NULL, sent_at DATETIME NOT NULL, responded_at DATETIME, expires_at DATETIME NOT NULL, requester_confirmed_at DATETIME, helper_confirmed_at DATETIME)")
    engine = make_engine(f"sqlite:///{path.as_posix()}")
    initialize_database(engine)
    initialize_database(engine)
    assert "message" in {column["name"] for column in inspect(engine).get_columns("help_offers")}
    assert "help_request_drafts" in inspect(engine).get_table_names()
    engine.dispose()
