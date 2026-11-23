"""The assistant over HTTP: attachments, the streamed chat (server-sent events), one run per thread, threads."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import server
from copilot import config


@pytest.fixture
def client():
    with TestClient(server.app) as c:   # `with` runs the lifespan: the graph and its SQLite checkpointer
        yield c


def events_of(response) -> list[dict]:
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    out = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        event = json.loads(data.removeprefix("data: "))
        assert name == f"event: {event['event']}"
        out.append(event)
    return out


def route(intent, countries=(), dates=()):
    return {"intent": intent, "countries": list(countries), "date_phrases": list(dates), "search_query": ""}


def test_chat_streams_progress_and_the_final_answer(client, fake_lm):
    fake_lm.script("route", route("out_of_scope"))
    events = events_of(client.post("/api/chat", json={"message": "Tell me a joke"}))
    assert events[0]["event"] == "thread" and len(events[0]["thread_id"]) == 32
    assert [e["event"] for e in events[1:]] == ["node_started", "node_finished", "node_started", "node_finished",
                                                 "final"]
    assert events[-1]["intent"] == "out_of_scope" and events[-1]["thread_id"] == events[0]["thread_id"]
    thread = client.get(f"/api/threads/{events[0]['thread_id']}").json()
    assert [m["role"] for m in thread["messages"]] == ["user", "assistant"]


def test_upload_an_invoice_and_validate_it_in_the_chat(client, fake_lm):
    xml = (config.SAMPLES_DIR / "ol-b2b-valid.xml").read_bytes()
    attachment_id = client.post("/api/attachments", content=xml).json()["attachment_id"]
    fake_lm.script("route", route("validate", ["OL"]))
    events = events_of(client.post("/api/chat", json={"message": "Check it", "thread_id": "api-validate",
                                                      "attachment_id": attachment_id,
                                                      "params": {"transaction_type": "B2B"}}))
    findings = next(e for e in events if e["event"] == "findings")["report"]
    assert findings["valid"] is True and findings["country"] == "OL"
    assert "no problems" in events[-1]["answer"]


def test_attachment_limits(client, monkeypatch):
    assert client.post("/api/attachments", content=b"").status_code == 422
    monkeypatch.setattr(config, "MAX_UPLOAD_KB", 1)
    assert client.post("/api/attachments", content=b"x" * 2048).status_code == 413


def test_chat_input_is_checked(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "thread_id": "../x"}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "attachment_id": "nope"}).status_code == 422
    assert client.post("/api/chat", json={"message": "hi", "params": {"stage": "later"}}).status_code == 422
    assert client.get("/api/threads/never-used").status_code == 404


def test_a_busy_thread_refuses_a_second_message(client, fake_lm):
    lock = server.thread_locks.setdefault("busy", asyncio.Lock())
    asyncio.run(lock.acquire())  # as if a run were in progress (an uncontended acquire binds no event loop)
    try:
        response = client.post("/api/chat", json={"message": "hi", "thread_id": "busy"})
        assert response.status_code == 409 and "still answering" in response.json()["detail"]
    finally:
        lock.release()
    fake_lm.script("route", route("out_of_scope"))
    assert events_of(client.post("/api/chat", json={"message": "hi", "thread_id": "busy"}))[-1]["event"] == "final"


def test_an_llm_outage_is_an_error_event_not_a_crash(client, fake_lm):
    fake_lm.fail_count = 1
    events = events_of(client.post("/api/chat", json={"message": "What is KSK?", "thread_id": "outage"}))
    assert events[-1]["event"] == "error" and "outage" not in server.thread_locks
