"""RestServiceNow: the ServiceNow Table API (`/api/now/table/{table}`) with Basic auth for an integration user.

Idempotency: the record carries `u_idempotency_key`; the client looks it up before inserting, so a retried request
or a second "create" for the same approved draft returns the existing ticket. (The lookup and the insert are two
calls; a unique index on the field in the instance would close the last race. Enough for one user per thread.)
One retry on 429 / 5xx / connection errors; every failure becomes a `TicketSystemError` with a message safe to show.
"""
import asyncio
import logging
import re

import httpx

from copilot import config
from copilot.integrations.servicenow.models import (
    RequirementDraft,
    TicketDetail,
    TicketRef,
    TicketSummary,
    TicketSystemError,
)

log = logging.getLogger("copilot.servicenow")
NUMBER = re.compile(r"^[A-Z]{2,10}\d{4,12}$")
KEY = re.compile(r"^[0-9a-f]{40}$")
FIELDS = ("number,sys_id,short_description,u_country,u_effective_date,u_user_story,u_acceptance_criteria,"
          "u_rule_ids,u_doc_refs,u_priority,u_idempotency_key,u_source_thread,sys_created_on")


class RestServiceNow:
    def __init__(self, instance_url: str | None = None, user: str | None = None, password: str | None = None,
                 table: str | None = None, transport: httpx.AsyncBaseTransport | None = None,
                 retry_delay: float = 1.0):
        self.instance_url = (instance_url or config.SN_INSTANCE_URL).rstrip("/")
        self.auth = (user or config.SN_USER, password or config.SN_PASSWORD)
        self.table = table or config.SN_TABLE
        self.transport = transport
        self.retry_delay = retry_delay
        if not self.instance_url.startswith("https://"):
            raise TicketSystemError("SN_INSTANCE_URL must be an https:// address.")

    def record_url(self, sys_id: str) -> str:
        return f"{self.instance_url}/{self.table}.do?sys_id={sys_id}"

    async def _request(self, method: str, params: dict | None = None, json: dict | None = None) -> dict:
        url = f"{self.instance_url}/api/now/table/{self.table}"
        async with httpx.AsyncClient(auth=self.auth, timeout=config.SN_TIMEOUT_SECONDS, transport=self.transport,
                                     headers={"Accept": "application/json"}) as client:
            for attempt in (1, 2):
                try:
                    response = await client.request(method, url, params=params, json=json)
                except httpx.HTTPError as exc:
                    if attempt == 1:
                        await asyncio.sleep(self.retry_delay)
                        continue
                    raise TicketSystemError(f"ServiceNow is not reachable ({type(exc).__name__}).") from exc
                if (response.status_code == 429 or response.status_code >= 500) and attempt == 1:
                    log.warning("ServiceNow %s %s: %s, retrying", method, self.table, response.status_code)
                    await asyncio.sleep(self.retry_delay)
                    continue
                break
        if response.status_code in (401, 403):
            raise TicketSystemError("ServiceNow refused the integration user (check SN_USER, SN_PASSWORD and "
                                    "its role on the table).")
        if response.status_code >= 400:
            raise TicketSystemError(f"ServiceNow answered {response.status_code} for the {self.table} table.")
        return response.json()

    async def create_requirement(self, draft: RequirementDraft, idempotency_key: str,
                                 source_thread: str) -> TicketRef:
        if not KEY.match(idempotency_key):  # it goes into an encoded query: hex only
            raise ValueError("idempotency key must be 40 hex characters")
        found = await self._request("GET", params={"sysparm_query": f"u_idempotency_key={idempotency_key}",
                                                   "sysparm_fields": "number,sys_id", "sysparm_limit": "1"})
        if found.get("result"):
            record = found["result"][0]
            return TicketRef(number=record["number"], sys_id=record["sys_id"],
                             url=self.record_url(record["sys_id"]), created=False)
        body = {"short_description": draft.title, "u_country": draft.country,
                "u_effective_date": draft.effective_date.isoformat() if draft.effective_date else "",
                "u_user_story": draft.user_story, "u_acceptance_criteria": "\n".join(draft.acceptance_criteria),
                "u_rule_ids": ",".join(draft.rule_ids), "u_doc_refs": "; ".join(draft.doc_refs),
                "u_priority": draft.priority, "u_idempotency_key": idempotency_key, "u_source_thread": source_thread}
        record = (await self._request("POST", params={"sysparm_fields": "number,sys_id"}, json=body))["result"]
        log.info("ServiceNow: created %s", record["number"])
        return TicketRef(number=record["number"], sys_id=record["sys_id"], url=self.record_url(record["sys_id"]),
                         created=True)

    def _summary(self, r: dict) -> dict:
        return {"number": r["number"], "title": r.get("short_description", ""), "country": r.get("u_country", ""),
                "effective_date": r.get("u_effective_date") or None, "priority": r.get("u_priority", ""),
                "created_at": r.get("sys_created_on", ""), "url": self.record_url(r["sys_id"])}

    async def get_ticket(self, number: str) -> TicketDetail | None:
        if not NUMBER.match(number):  # never let a caller's text into the encoded query
            return None
        found = await self._request("GET", params={"sysparm_query": f"number={number}", "sysparm_fields": FIELDS,
                                                   "sysparm_limit": "1"})
        if not found.get("result"):
            return None
        r = found["result"][0]
        return TicketDetail(**self._summary(r), user_story=r.get("u_user_story", ""),
                            acceptance_criteria=[c for c in r.get("u_acceptance_criteria", "").split("\n") if c],
                            rule_ids=[i for i in r.get("u_rule_ids", "").split(",") if i],
                            doc_refs=[d for d in r.get("u_doc_refs", "").split("; ") if d],
                            source_thread=r.get("u_source_thread", ""),
                            idempotency_key=r.get("u_idempotency_key", ""))

    async def list_recent(self, limit: int = 20) -> list[TicketSummary]:
        found = await self._request("GET", params={"sysparm_query": "ORDERBYDESCsys_created_on",
                                                   "sysparm_fields": FIELDS, "sysparm_limit": str(limit)})
        return [TicketSummary(**self._summary(r)) for r in found.get("result", [])]
