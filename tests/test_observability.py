"""Runs and spans (ARCHITECTURE.md §11): one run per request, one span per node with tokens and documents, the trace
and the metrics over HTTP."""
import pytest
from fastapi.testclient import TestClient
from test_chat_api import events_of, route, scripted_draft

import server
from copilot import config, observability


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DB", tmp_path / "app.sqlite")      # metrics count only this test's runs
    with TestClient(server.app) as c:
        yield c


def chat(client, **body):
    return events_of(client.post("/api/chat", json=body))


def test_a_run_is_stored_with_a_span_per_node(client, fake_lm):
    fake_lm.script("route", route("out_of_scope"))
    events = chat(client, message="Tell me a joke")
    run_id = events[1]["run_id"]
    trace = client.get(f"/api/runs/{run_id}/trace").json()
    assert trace["status"] == "ok" and [s["node"] for s in trace["spans"]] == ["route", "out_of_scope"]
    route_span = trace["spans"][0]
    assert (route_span["tokens_in"], route_span["tokens_out"], route_span["llm_calls"]) == (100, 20, 1)
    assert trace["spans"][1]["llm_calls"] == 0 and trace["spans"][1]["tokens_in"] is None
    run = client.get(f"/api/runs/{run_id}").json()
    assert run["intent"] == "out_of_scope" and run["final"]["answer"] == events[-1]["answer"]
    assert run["model"] == config.LLM_MODEL and run["ms"] >= sum(s["ms"] for s in trace["spans"])
    assert client.get("/api/runs/" + "0" * 32).status_code == 404
    assert client.get("/api/runs/not-a-run").status_code == 422


def test_retrieved_documents_and_abstention_are_recorded(client, fake_lm):
    fake_lm.script("route", route("question", ["KS"]))
    fake_lm.script("grounded_answer", {"in_documents": False, "answer": ""})
    events = chat(client, message="What is the corporate income tax rate in Kestria?")
    run = client.get(f"/api/runs/{events[1]['run_id']}").json()
    retrieve = next(s for s in run["spans"] if s["node"] == "retrieve")
    assert retrieve["doc_ids"] and all(d.startswith(("KS-", "COM-")) for d in retrieve["doc_ids"])
    assert run["abstained"] == (0 if events[-1]["citations"] else 1)


def test_the_approval_flow_is_two_runs_and_the_metrics_add_up(client, fake_lm):
    fake_lm.script("route", route("draft_requirement", ["OL"], ["1 April 2026"]))
    fake_lm.script("requirement_draft", scripted_draft)
    chat(client, message="Draft a requirement for the Orlavia deadline", thread_id="obs-ticket")
    events = chat(client, message="Create ticket", thread_id="obs-ticket", action="create_ticket")
    waiting = next(e for e in events if e["event"] == "approval")
    assert client.get(f"/api/runs/{events[1]['run_id']}").json()["status"] == "waiting"
    events = events_of(client.post("/api/threads/obs-ticket/approval",
                                   json={"interrupt_id": waiting["interrupt_id"], "approved": True}))
    run = client.get(f"/api/runs/{events[1]['run_id']}").json()
    assert run["kind"] == "approval" and run["approved"] == 1 and run["ticket"].startswith("LOCREQ")
    assert [s["node"] for s in run["spans"]] == ["approval", "create_ticket"]

    m = client.get("/api/metrics").json()
    assert m["runs"] == 3 and m["runs_per_intent"]["create_ticket"] == 2
    assert m["tickets_created"] == 1 and m["approvals"] == {"approved": 1, "rejected": 0}
    assert m["failed_runs"] == 0 and m["llm_errors"] == 0
    assert set(m["latency_ms"]["nodes"]) >= {"route", "retrieve", "draft_requirement", "approval", "create_ticket"}
    assert m["latency_ms"]["end_to_end"]["n"] == 3 and m["tokens"]["in"] >= 200


def test_an_llm_outage_marks_the_run_failed(client):
    events = chat(client, message="How long are invoices archived in Kestria?")   # LM Studio is not reachable
    assert events[-1]["event"] == "error"
    run = client.get(f"/api/runs/{events[1]['run_id']}").json()
    assert run["status"] == "failed" and run["spans"][0]["status"] == "error"
    assert client.get("/api/metrics").json()["llm_errors"] == 1


def test_percentiles_and_an_empty_store():
    assert observability.percentile([], 50) is None
    assert observability.percentile([10, 20, 30, 40], 50) == 20 and observability.percentile([10, 20, 30, 40], 95) == 40
