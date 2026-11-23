"""HTTP API of E1: health, corpus and rule definitions."""
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

import server
from copilot import config


@pytest.fixture
def client():
    return TestClient(server.app)


def test_health_reports_counts_and_an_unreachable_llm(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok" and data["llm"]["reachable"] is False
    assert data["corpus"]["documents"] == 14 and data["rules"]["count"] == 30  # the test-only doc is not loaded
    assert data["today"] == "2026-05-15"


class ModelsHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        self.send_response(200 if self.path.endswith("/models") else 404)
        self.end_headers()
        self.wfile.write(b'{"data": []}')

    def log_message(self, *args):
        pass


def test_a_running_llm_server_is_reported_reachable(monkeypatch):
    httpd = HTTPServer(("127.0.0.1", 0), ModelsHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(config, "LLM_BASE_URL", f"http://127.0.0.1:{httpd.server_port}/v1")
        assert asyncio.run(server.llm_reachable()) is True
    finally:
        httpd.shutdown()


def test_corpus_list_and_one_document(client):
    docs = client.get("/api/corpus").json()["documents"]
    assert len(docs) == 14 and {d["country"] for d in docs} == {"VD", "KS", "OL", "COMMON"}
    doc = client.get("/api/corpus/vd-am-03").json()
    assert doc["valid_from"] == "2026-03-10" and doc["announces"] == ["2026-07-01"]
    assert doc["sections"][1]["heading"] == "Amendment to Article 4(3)" and "body" not in doc
    assert client.get("/api/corpus/XX-99").status_code == 404


def test_rules_for_an_invoice(client):
    everything = client.get("/api/rules").json()
    assert len(everything["rules"]) == 30 and everything["code_lists"]["invoice_type"] == ["380", "381"]
    cleared = client.get("/api/rules", params={"country": "VD", "as_of": "2026-02-01", "stage": "cleared"}).json()
    assert "VD-09" in {r["id"] for r in cleared["rules"]}
    orlavia = client.get("/api/rules", params={"country": "OL", "transaction_type": "B2C"}).json()
    assert orlavia["code_lists"]["invoice_type"] == ["380", "381", "389"]
    assert client.get("/api/rules", params={"country": "XX"}).status_code == 422
