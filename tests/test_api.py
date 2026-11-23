"""HTTP API: health, corpus, rule definitions, validation and samples."""
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


def test_a_running_llm_server_is_reported_reachable(monkeypatch, client):
    httpd = HTTPServer(("127.0.0.1", 0), ModelsHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(config, "LLM_BASE_URL", f"http://127.0.0.1:{httpd.server_port}/v1")
        # Through the app, not asyncio.run(): the Playwright tests keep an event loop running in this thread.
        assert client.get("/api/health").json()["llm"]["reachable"] is True
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


# --- E2: validation and samples ------------------------------------------------------------------------------------

def sample_xml(client, name):
    response = client.get(f"/api/samples/{name}")
    assert response.status_code == 200 and response.headers["content-type"].startswith("application/xml")
    return response.content


def test_validate_a_sample_over_http(client):
    report = client.post("/api/validate", content=sample_xml(client, "ks-demo-old-rate-no-ksk-total")).json()
    assert report["country"] == "KS" and report["valid"] is False
    assert [f["rule_id"] for f in report["findings"]] == ["KS-04", "KS-05"]
    assert report["findings"][1]["doc_ref"] == ["KS-CL-01 §2", "KS-TS-01 §5"]


def test_validate_with_parameters(client):
    data = sample_xml(client, "ks-b2b-valid")
    report = client.post("/api/validate", params={"transaction_type": "B2G"}, content=data).json()
    assert [f["rule_id"] for f in report["findings"]] == ["KS-06"]
    assert client.post("/api/validate", params={"stage": "later"}, content=data).status_code == 422


def test_validate_rejects_oversized_bodies_and_reports_bad_xml(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_KB", 1)
    assert client.post("/api/validate", content=b"x" * 2048).status_code == 413
    report = client.post("/api/validate", content=b"not xml").json()
    assert [f["rule_id"] for f in report["findings"]] == ["XML-00"]


def test_sample_list_and_unknown_samples(client):
    listed = client.get("/api/samples").json()["samples"]
    demo = next(s for s in listed if s["name"] == "ks-demo-old-rate-no-ksk-total")
    assert demo["expected_rule_ids"] == ["KS-04", "KS-05"] and demo["params"] == {}
    assert client.get("/api/samples/nope").status_code == 404
    assert client.get("/api/samples/..%2Fgenerator.py").status_code == 404


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200 and "<title>E-Invoice Compliance Copilot</title>" in response.text
