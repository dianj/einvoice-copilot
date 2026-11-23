"""draft_requirement → (a later "create the ticket") → approval (interrupt) → create_ticket.

The model drafts a requirement from the retrieved passages; code checks the draft before anyone sees it: every
document reference must be a retrieved passage, every rule id must belong to the country, the effective date must
appear in a cited passage (or it is flagged), and the priority is computed from that date, not chosen by the model.

A ticket needs a person: `approval` pauses the graph with `interrupt()` and resumes only with a decision sent by the
UI's Approve / Reject buttons (`POST /api/threads/{id}/approval`). The decision is checked again here (only the
editable fields, valid values). `create_ticket` runs only after an approval of exactly the current draft, and once
per approved draft: the idempotency key returns the existing ticket on a second request.
"""
import asyncio
import re
from datetime import date

from langgraph.config import get_config
from langgraph.types import interrupt
from pydantic import ValidationError

from copilot.graph import prompts
from copilot.graph.nodes.common import reply, traced, unique_passages
from copilot.graph.texts import text
from copilot.integrations.servicenow import TicketSystemError, ticket_system
from copilot.integrations.servicenow.models import (
    EDITABLE,
    DraftEdits,
    RequirementDraft,
    draft_hash,
    idempotency_key,
)
from copilot.llm import complete_json
from copilot.rules.definitions import rules

MONTHS = ("january february march april may june july august september october november december").split()
LONG_DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(MONTHS) + r") (20\d{2})\b", re.I)
ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
HIGH_WITHIN_DAYS = 183  # obligations starting within about six months (or already in force) are high priority


def dates_in(text_: str) -> set[date]:
    found = set()
    for d, month, y in LONG_DATE.findall(text_):
        try:
            found.add(date(int(y), MONTHS.index(month.lower()) + 1, int(d)))
        except ValueError:
            pass
    for y, m, d in ISO_DATE.findall(text_):
        try:
            found.add(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return found


def priority_for(effective: date | None, as_of: date) -> str:
    if effective is None:
        return "medium"
    return "high" if (effective - as_of).days <= HIGH_WITHIN_DAYS else "medium"


def check_draft(data: dict, passages: list[dict], allowed_rules: dict[str, str], as_of: date,
                lang: str) -> tuple[dict | None, list[str]]:
    """The model's draft after the code checks: (draft or None, notes for the user)."""
    notes = []
    by_ref = {p["ref"]: p for p in passages}
    refs = [r for r in dict.fromkeys(data.get("doc_refs") or []) if r in by_ref]
    if not refs:
        return None, ["The draft cited no retrieved passage, so it was not shown."]
    country = data.get("country")
    rule_ids = []
    for rule_id in dict.fromkeys(data.get("rule_ids") or []):
        if allowed_rules.get(rule_id) in (country, "CORE"):
            rule_ids.append(rule_id)
        else:
            notes.append(f"Removed rule {rule_id}: it does not belong to {country}.")
    warnings = []
    effective = None
    raw_date = str(data.get("effective_date") or "").strip()
    if raw_date:
        try:
            effective = date.fromisoformat(raw_date)
        except ValueError:
            warnings.append(text(lang, "warn_bad_date", value=raw_date[:40]))
    if effective:
        cited = [by_ref[r] for r in refs]
        stated = set().union(*(dates_in(p["text"]) | dates_in(p["heading"]) for p in cited))
        starts = {date.fromisoformat(p["valid_from"]) for p in cited if p.get("valid_from")}
        if effective not in stated | starts:
            warnings.append(text(lang, "warn_unverified_date", value=effective.isoformat()))
    elif not raw_date:
        warnings.append(text(lang, "warn_no_date"))
    criteria = [c.strip() for c in data.get("acceptance_criteria") or [] if str(c).strip()][:8]
    try:
        draft = RequirementDraft(
            title=str(data.get("title", "")).strip()[:160], country=country, effective_date=effective,
            user_story=str(data.get("user_story", "")).strip()[:4000], acceptance_criteria=criteria,
            rule_ids=rule_ids, doc_refs=refs, priority=priority_for(effective, as_of), as_of=as_of,
            warnings=warnings)
    except ValidationError as exc:
        return None, [f"The draft was incomplete ({exc.error_count()} problems), so it was not shown."]
    return draft.model_dump(mode="json"), notes


def render_draft(draft: dict, lang: str) -> str:
    country = prompts.COUNTRY_NAMES[draft["country"]]
    lines = [f"{text(lang, 'draft_heading')}: {draft['title']}",
             text(lang, "draft_meta", country=country, date=draft["effective_date"] or "?",
                  priority=draft["priority"]),
             "", f"{text(lang, 'user_story')}: {draft['user_story']}", "", f"{text(lang, 'acceptance')}:"]
    lines += [f"- {c}" for c in draft["acceptance_criteria"]]
    if draft["rule_ids"]:
        lines += ["", f"{text(lang, 'rules')}: {', '.join(draft['rule_ids'])}"]
    lines += ["", text(lang, "offer_ticket")]
    return "\n".join(lines)


@traced("draft_requirement")
async def draft_requirement(state) -> dict:
    lang = state["language"]
    retrievals = state.get("retrievals", [])
    if not any(r["answerable"] for r in retrievals):
        return reply(text(lang, "draft_no_sources"), citations=[])
    passages = unique_passages([r["passages"] for r in retrievals])
    as_of = date.fromisoformat(state["dates"][0])
    countries = state["countries"]
    rule_set = await asyncio.to_thread(rules)
    candidates = [r for r in rule_set.all if r.country in countries or r.country == "CORE"]
    allowed = {r.id: r.country for r in candidates}
    rule_lines = [f"- {r.id}: {r.title} (rests on {', '.join(r.doc_ref) or 'no document'})" for r in candidates]
    result = await complete_json(
        prompts.DRAFT_SYSTEM.format(language=prompts.LANGUAGE_NAMES[lang], as_of=as_of.isoformat()),
        prompts.draft_user(state["user_input"], passages, rule_lines),
        prompts.draft_schema(countries, [p["ref"] for p in passages], list(allowed)), "requirement_draft")
    draft, notes = check_draft(result.data, passages, allowed, as_of, lang)
    notes = list(state.get("notes", [])) + notes
    if draft is None:
        return reply(text(lang, "draft_failed"), citations=[], notes=notes)
    return reply(render_draft(draft, lang), requirement_draft=draft, citations=draft["doc_refs"], notes=notes)


def apply_decision(decision, draft: dict) -> tuple[dict | None, str]:
    """(the draft to create a ticket for, or None; a note). Anything but a well-formed approval is a rejection."""
    if not isinstance(decision, dict) or decision.get("approved") is not True:
        return None, ""
    try:
        edits = DraftEdits.model_validate(decision.get("edits") or {}).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        return None, f"The edits were not valid ({exc.error_count()} problems): nothing was created."
    changed = [k for k in EDITABLE if k in edits and edits[k] != draft.get(k)]
    if not changed:
        return draft, ""
    updated = {**draft, **{k: edits[k] for k in changed}}
    updated["edited"] = sorted(set(draft.get("edited", [])) | set(changed))
    if "effective_date" in changed:
        updated["warnings"] = [*draft.get("warnings", []), "The effective date was edited at approval and is not "
                                                          "checked against the documents."]
    note = f"Edited at approval: {', '.join(changed)}."
    return RequirementDraft.model_validate(updated).model_dump(mode="json"), note


@traced("approval")
async def approval(state) -> dict:
    lang = state["language"]
    draft = state.get("requirement_draft")
    decision = interrupt({"kind": "ticket_approval", "draft": draft, "editable": list(EDITABLE)})
    approved, note = apply_decision(decision, draft)
    notes = [note] if note else []
    if approved is None:
        return {"approval": {"approved": False}, **reply(text(lang, "ticket_rejected"), notes=notes)}
    return {"approval": {"approved": True, "draft_hash": draft_hash(approved)}, "requirement_draft": approved,
            "notes": notes}


def after_approval(state) -> str:
    return "create_ticket" if (state.get("approval") or {}).get("approved") is True else "end"


@traced("create_ticket")
async def create_ticket(state) -> dict:
    lang = state["language"]
    draft = state.get("requirement_draft")
    decision = state.get("approval") or {}
    if not draft or decision.get("approved") is not True or decision.get("draft_hash") != draft_hash(draft):
        return reply(text(lang, "ticket_not_approved"))  # never reached through the graph; a second lock
    thread_id = get_config()["configurable"]["thread_id"]
    try:
        ref = await ticket_system().create_requirement(RequirementDraft.model_validate(draft),
                                                       idempotency_key(thread_id, draft), thread_id)
    except TicketSystemError as exc:
        return reply(text(lang, "ticket_failed", reason=str(exc)), notes=list(state.get("notes", [])))
    key = "ticket_created" if ref.created else "ticket_exists"
    return reply(text(lang, key, number=ref.number), ticket=ref.model_dump(), citations=draft["doc_refs"],
                 notes=list(state.get("notes", [])))
