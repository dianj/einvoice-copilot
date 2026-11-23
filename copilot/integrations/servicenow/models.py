"""The requirement draft, ticket references and the ticket-system interface.

A draft is what the model proposed and code checked; `DraftEdits` is the only shape a user's edits may take at the
approval step (also checked again inside the graph). The idempotency key ties a ticket to one approved draft in one
conversation: asking twice for the same draft returns the existing ticket.
"""
import hashlib
import json
from datetime import date
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Priority = Literal["low", "medium", "high"]
EDITABLE = ("title", "user_story", "acceptance_criteria", "priority", "effective_date")


class TicketSystemError(Exception):
    """The ticket system could not be reached or refused the request (message safe to show)."""


class RequirementDraft(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    country: Literal["VD", "KS", "OL"]
    effective_date: date | None = None
    user_story: str = Field(min_length=1, max_length=4000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=8)
    rule_ids: list[str] = []
    doc_refs: list[str] = Field(min_length=1)
    priority: Priority
    as_of: date
    warnings: list[str] = []          # what code could not confirm (shown on the approval card)
    edited: list[str] = []            # fields the user changed at approval


class DraftEdits(BaseModel):
    """The fields a user may change before approving. Rule ids and document references are evidence: not editable."""
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=3, max_length=160)
    user_story: str | None = Field(None, min_length=1, max_length=4000)
    acceptance_criteria: list[str] | None = Field(None, min_length=1, max_length=8)
    priority: Priority | None = None
    effective_date: date | None = None


class TicketRef(BaseModel):
    number: str
    sys_id: str
    url: str | None = None
    created: bool                     # False: a ticket for this approved draft existed already


class TicketSummary(BaseModel):
    number: str
    title: str
    country: str
    effective_date: str | None
    priority: str
    created_at: str
    url: str | None = None


class TicketDetail(TicketSummary):
    user_story: str
    acceptance_criteria: list[str]
    rule_ids: list[str]
    doc_refs: list[str]
    source_thread: str
    idempotency_key: str


class TicketSystem(Protocol):
    async def create_requirement(self, draft: RequirementDraft, idempotency_key: str,
                                 source_thread: str) -> TicketRef: ...

    async def get_ticket(self, number: str) -> TicketDetail | None: ...

    async def list_recent(self, limit: int = 20) -> list[TicketSummary]: ...


def draft_hash(draft: dict) -> str:
    """A stable hash of the draft's content (what an approval approved)."""
    canonical = json.dumps(draft, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def idempotency_key(thread_id: str, draft: dict) -> str:
    return hashlib.sha256(f"{thread_id}\n{draft_hash(draft)}".encode()).hexdigest()[:40]
