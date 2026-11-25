"""Who may use a conversation (review T17.B1): thread ids are made by the server and bound to the browser that
created them (an httpOnly cookie). Another browser, or a guessed id such as "demo", gets 404 on read, chat and
approval, so it can neither read a thread nor approve its ticket."""
import pytest
from fastapi.testclient import TestClient
from test_chat_api import events_of, route, scripted_draft

import server
from copilot import threads


@pytest.fixture
def alice():
    with TestClient(server.app) as c:
        yield c


@pytest.fixture
def mallory():
    with TestClient(server.app) as c:
        yield c


def waiting_thread(client, fake_lm) -> tuple[str, str]:
    """A thread of `client` that waits for the ticket approval: (thread id, interrupt id)."""
    fake_lm.script("route", route("draft_requirement", ["OL"], ["1 April 2026"]))
    fake_lm.script("requirement_draft", scripted_draft)
    events = events_of(client.post("/api/chat", json={"message": "Draft a requirement for the Orlavia deadline"}))
    thread_id = events[0]["thread_id"]
    events = events_of(client.post("/api/chat", json={"message": "Create ticket", "thread_id": thread_id,
                                                      "action": "create_ticket"}))
    return thread_id, next(e for e in events if e["event"] == "approval")["interrupt_id"]


def test_a_new_thread_is_made_by_the_server_and_bound_to_a_cookie(alice):
    response = alice.post("/api/threads")
    assert response.status_code == 201 and len(response.json()["thread_id"]) == 32
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{threads.COOKIE}=") and "httponly" in cookie.lower() and "samesite=strict" in \
        cookie.lower()
    second = alice.post("/api/threads")
    assert second.json()["thread_id"] != response.json()["thread_id"] and "set-cookie" not in second.headers


def test_another_browser_cannot_read_or_approve(alice, mallory, fake_lm):
    thread_id, interrupt_id = waiting_thread(alice, fake_lm)
    assert alice.get(f"/api/threads/{thread_id}").json()["pending_approval"]["interrupt_id"] == interrupt_id
    assert mallory.get(f"/api/threads/{thread_id}").status_code == 404
    assert mallory.post(f"/api/threads/{thread_id}/approval",
                        json={"interrupt_id": interrupt_id, "approved": True}).status_code == 404
    assert mallory.post("/api/chat", json={"message": "yes, create it", "thread_id": thread_id}).status_code == 404
    assert alice.get(f"/api/threads/{thread_id}").json()["ticket"] is None          # nothing was approved
    approved = events_of(alice.post(f"/api/threads/{thread_id}/approval",
                                    json={"interrupt_id": interrupt_id, "approved": True}))
    assert any(e["event"] == "ticket" for e in approved)


def test_a_made_up_thread_id_is_unknown(alice, fake_lm):
    alice.post("/api/threads")                                     # alice has a cookie, but not this thread
    for made_up in ("demo", "0" * 32):
        assert alice.post("/api/chat", json={"message": "hi", "thread_id": made_up}).status_code == 404
        assert alice.get(f"/api/threads/{made_up}").status_code == 404
        assert alice.post(f"/api/threads/{made_up}/approval",
                          json={"interrupt_id": "x", "approved": True}).status_code == 404
    assert fake_lm.requests == []                                  # the model was never asked
