"""A stand-in for the ServiceNow Table API (`/api/now/table/{table}`) as an `httpx.MockTransport`.

Enough of the real behaviour for the REST adapter's tests: Basic auth, `sysparm_query` with `field=value` and
`ORDERBYDESCsys_created_on`, `sysparm_fields`, `sysparm_limit`, POST returning the record with a generated number and
sys_id. Failure modes: `down` (503 for every call), `fail_next` (the next N calls get 503), `rate_limited_next` (429).
"""
import base64
import itertools
import json
from urllib.parse import parse_qs

import httpx

INSTANCE = "https://dev00000.service-now.com"
USER, PASSWORD = "copilot.integration", "test-password"
TABLE = "u_localization_requirement"


class FakeServiceNowAPI:
    def __init__(self):
        self.records: list[dict] = []
        self.calls: list[tuple[str, str]] = []
        self.down = False
        self.fail_next = 0
        self.rate_limited_next = 0
        self._seq = itertools.count(1001)
        self._clock = itertools.count(0)
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        expected = "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"error": {"message": "User Not Authenticated"}})
        if self.down:
            return httpx.Response(503, text="Instance hibernating")
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503, text="Service Unavailable")
        if self.rate_limited_next:
            self.rate_limited_next -= 1
            return httpx.Response(429, json={"error": {"message": "Rate limit exceeded"}})
        if request.url.path != f"/api/now/table/{TABLE}":
            return httpx.Response(400, json={"error": {"message": "Invalid table"}})
        params = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        fields = params.get("sysparm_fields", "").split(",") if params.get("sysparm_fields") else None
        if request.method == "POST":
            body = json.loads(request.content)
            seq = next(self._seq)
            record = {**{k: str(v) for k, v in body.items()}, "number": f"LOCREQ{seq:07d}",
                      "sys_id": f"{seq:032x}", "sys_created_on": f"2026-11-24 10:{next(self._clock):02d}:00"}
            self.records.append(record)
            return httpx.Response(201, json={"result": self._select(record, fields)})
        if request.method == "GET":
            rows = list(self.records)
            for part in params.get("sysparm_query", "").split("^"):
                if part == "ORDERBYDESCsys_created_on":
                    rows.sort(key=lambda r: r["sys_created_on"], reverse=True)
                elif "=" in part:
                    field, value = part.split("=", 1)
                    rows = [r for r in rows if r.get(field) == value]
            rows = rows[:int(params.get("sysparm_limit", "10000"))]
            return httpx.Response(200, json={"result": [self._select(r, fields) for r in rows]})
        return httpx.Response(405)

    @staticmethod
    def _select(record: dict, fields: list[str] | None) -> dict:
        return {k: record.get(k, "") for k in fields} if fields else dict(record)
