from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from faqbot.api import create_app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        EXAMPLES / "camp" / "kb.yaml",
        unanswered_path=tmp_path / "unanswered.jsonl",
        feedback_path=tmp_path / "feedback.jsonl",
    )
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "qa": 25, "bot": "Солнышко"}


def test_config(client):
    data = client.get("/api/config").json()
    assert data["botName"] == "Солнышко"
    assert data["quick"]
    assert data["operator"].startswith("https://t.me/")


def test_ask(client):
    response = client.post(
        "/api/ask", json={"message": "сколько стоит путёвка", "session": "test-1"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["matched"] is True
    assert data["qa_id"] == 1
    assert data["score"] == 1.0
    assert data["session"] == "test-1"


def test_ask_rejects_empty_message(client):
    assert client.post("/api/ask", json={"message": ""}).status_code == 422


def test_unanswered_questions_are_logged(client, tmp_path):
    client.post("/api/ask", json={"message": "расскажи про марсианские хроники"})
    log = tmp_path / "unanswered.jsonl"
    assert log.exists()
    assert "марсианские" in log.read_text(encoding="utf-8")


def test_feedback_is_logged(client, tmp_path):
    response = client.post(
        "/api/feedback", json={"session": "s", "qa_id": 1, "value": 1}
    )
    assert response.json() == {"ok": True}
    assert '"qa_id": 1' in (tmp_path / "feedback.jsonl").read_text(encoding="utf-8")


def test_search_endpoint(client):
    matches = client.get("/api/search", params={"q": "документы"}).json()["matches"]
    assert matches
    assert matches[0]["id"] == 10
    assert 0 <= matches[0]["score"] <= 1


def test_widget_assets_are_served(client):
    assert "fb-root" in client.get("/widget.js").text
    assert "--fb-accent" in client.get("/widget.css").text
    assert "faqbot" in client.get("/").text
