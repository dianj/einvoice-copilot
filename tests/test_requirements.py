"""Requirement drafts and tickets: the code checks on a draft, and no ticket without a person's approval."""
import asyncio
from datetime import date

import pytest
from fake_lmstudio import enum_of, user_prompt
from langgraph.checkpoint.memory import InMemorySaver

from copilot.graph.build import build_graph
from copilot.graph.nodes.requirement import apply_decision, check_draft, dates_in, priority_for
from copilot.graph.run import stream_resume, stream_turn
from copilot.integrations.servicenow import FakeServiceNow
from copilot.integrations.servicenow.models import draft_hash


@pytest.fixture
def graph():
    return build_graph(InMemorySaver())


@pytest.fixture
def tickets(tmp_path, monkeypatch):
    """A fresh local ticket table per test."""
    store = FakeServiceNow(tmp_path / "tickets.sqlite")
    monkeypatch.setattr("copilot.graph.nodes.requirement.ticket_system", lambda: store)
    return store


def run(graph, message, thread="r1", action=None) -> list[dict]:
    async def collect():
        return [e async for e in stream_turn(graph, thread, message, action=action)]
    return asyncio.run(collect())


def resume(graph, decision, thread="r1") -> list[dict]:
    async def collect():
        return [e async for e in stream_resume(graph, thread, decision)]
    return asyncio.run(collect())


def nodes(events) -> list[str]:
    return [e["node"] for e in events if e["event"] == "node_started"]


def of(events, name) -> list[dict]:
    return [e for e in events if e["event"] == name]


def route(intent, countries=("OL",), dates=("1 April 2026",)):
    return {"intent": intent, "countries": list(countries), "date_phrases": list(dates),
            "search_query": "Orlavia ORTS reporting deadline hours after issue"}


def draft_answer(effective="2026-04-01"):
    """A draft citing the first offered passage of the deadline decree (or the first passage) and rule OL-05."""
    def respond(payload):
        refs = enum_of(payload, "doc_refs")
        ref = next((r for r in refs if r.startswith("OL-AM-12")), refs[0])
        return {"title": "Orlavia: report invoices to ORTS within 4 hours", "country": "OL",
                "effective_date": effective, "user_story": "As a localization analyst, I want the 4-hour deadline.",
                "acceptance_criteria": ["Invoices issued from 1 April 2026 are reported within 4 hours.", " "],
                "rule_ids": ["OL-05"], "doc_refs": [ref, ref]}
    return respond


def make_draft(graph, fake_lm, **answer) -> dict:
    fake_lm.script("route", route("draft_requirement"))
    fake_lm.script("requirement_draft", draft_answer(**answer))
    events = run(graph, "Draft a requirement for the Orlavia reporting deadline from 1 April 2026")
    assert nodes(events) == ["route", "extract_date", "retrieve", "draft_requirement"]
    return of(events, "draft")[0]["draft"]


# --- drafting ----------------------------------------------------------------------------------------------------

def test_a_draft_is_checked_by_code_and_offered_as_a_ticket(graph, fake_lm, tickets):
    draft = make_draft(graph, fake_lm)
    assert draft["country"] == "OL" and draft["effective_date"] == "2026-04-01" and draft["as_of"] == "2026-04-01"
    assert draft["rule_ids"] == ["OL-05"]
    assert len(draft["doc_refs"]) == 1 and draft["doc_refs"][0].startswith("OL-AM-12")
    assert draft["acceptance_criteria"] == ["Invoices issued from 1 April 2026 are reported within 4 hours."]
    assert draft["priority"] == "high" and draft["warnings"] == []
    call = fake_lm.calls("requirement_draft")[0]
    assert set(enum_of(call, "country")) == {"OL"}
    assert all(r.split("-")[0] in ("OL", "CORE") for r in enum_of(call, "rule_ids"))
    assert "OL-05:" in user_prompt(call)
    assert asyncio.run(tickets.list_recent()) == []           # a draft is never a ticket


def test_an_effective_date_not_in_the_cited_passages_is_flagged(graph, fake_lm, tickets):
    draft = make_draft(graph, fake_lm, effective="2026-09-30")
    assert any("2026-09-30" in w and "does not appear" in w for w in draft["warnings"])


def test_a_draft_needs_a_country_and_passages(graph, fake_lm, tickets):
    fake_lm.script("route", route("draft_requirement", countries=()))
    events = run(graph, "Draft a requirement for that change")
    assert nodes(events) == ["route", "clarify"] and "Name the country" in events[-1]["answer"]
    fake_lm.script("route", route("draft_requirement"))
    fake_lm.script("requirement_draft", lambda p: {**draft_answer()(p), "title": ""})  # incomplete
    events = run(graph, "Draft a requirement for the Orlavia deadline", thread="r2")
    assert "could not produce" in events[-1]["answer"] and not of(events, "draft")


def test_check_draft_unit():
    passages = [{"ref": "OL-AM-12 §2", "heading": "2. New deadline", "valid_from": "2025-11-01",
                 "text": "Invoices issued from 1 April 2026 shall be reported within 4 hours."}]
    allowed = {"OL-05": "OL", "CORE-01": "CORE", "VD-01": "VD"}
    base = {"title": "Deadline", "country": "OL", "effective_date": "2026-04-01", "user_story": "As ...",
            "acceptance_criteria": ["x"], "rule_ids": ["OL-05", "CORE-01", "VD-01"], "doc_refs": ["OL-AM-12 §2"]}
    draft, notes = check_draft(base, passages, allowed, date(2026, 1, 10), "en")
    assert draft["rule_ids"] == ["OL-05", "CORE-01"] and notes == ["Removed rule VD-01: it does not belong to OL."]
    assert check_draft({**base, "effective_date": "2025-11-01"}, passages, allowed, date(2026, 1, 1), "en")[0][
        "warnings"] == []                                        # the passage's own start date counts too
    assert "not a date" in check_draft({**base, "effective_date": "soon"}, passages, allowed,
                                       date(2026, 1, 1), "en")[0]["warnings"][0]
    no_date = check_draft({**base, "effective_date": ""}, passages, allowed, date(2026, 1, 1), "bg")[0]
    assert no_date["effective_date"] is None and no_date["priority"] == "medium" and "Откъсите" in no_date[
        "warnings"][0]
    assert check_draft({**base, "doc_refs": ["XX-LAW-99 §1"]}, passages, allowed, date(2026, 1, 1), "en")[0] is None


def test_dates_and_priority():
    assert dates_in("from 1 April 2026 and 2026-07-01, not 31 February 2026") == {date(2026, 4, 1),
                                                                                  date(2026, 7, 1)}
    assert dates_in("2026-13-01") == set()
    assert priority_for(date(2026, 6, 1), date(2026, 5, 15)) == "high"
    assert priority_for(date(2026, 1, 1), date(2026, 5, 15)) == "high"        # already in force
    assert priority_for(date(2027, 6, 1), date(2026, 5, 15)) == "medium"
    assert priority_for(None, date(2026, 5, 15)) == "medium"


# --- approval and tickets ----------------------------------------------------------------------------------------

def ask_for_ticket(graph, fake_lm, message="Yes, create the ticket", **kwargs) -> list[dict]:
    if kwargs.get("action") is None:
        fake_lm.script("route", route("create_ticket", dates=()))
    return run(graph, message, **kwargs)


def test_approve_creates_exactly_one_ticket(graph, fake_lm, tickets):
    draft = make_draft(graph, fake_lm)
    events = ask_for_ticket(graph, fake_lm)
    assert nodes(events) == ["route", "approval"]
    waiting = of(events, "approval")[0]
    assert waiting["draft"] == draft and "priority" in waiting["editable"] and waiting["interrupt_id"]
    assert events[-1]["awaiting_approval"] is True and "No ticket is created" in events[-1]["answer"]
    assert asyncio.run(tickets.list_recent()) == []           # waiting is not approving

    events = resume(graph, {"approved": True})
    assert nodes(events) == ["approval", "create_ticket"]
    ticket = of(events, "ticket")[0]["ticket"]
    assert ticket["created"] and ticket["number"] == "LOCREQ0001001"
    assert "Created ServiceNow ticket LOCREQ0001001" in events[-1]["answer"]
    assert [t.number for t in asyncio.run(tickets.list_recent())] == ["LOCREQ0001001"]

    # asking again for the same approved draft: approval again, then the existing ticket
    ask_for_ticket(graph, fake_lm, action="create_ticket")
    events = resume(graph, {"approved": True})
    assert "exists already: LOCREQ0001001" in events[-1]["answer"]
    assert len(asyncio.run(tickets.list_recent())) == 1


def test_reject_creates_nothing_and_keeps_the_draft(graph, fake_lm, tickets):
    draft = make_draft(graph, fake_lm)
    ask_for_ticket(graph, fake_lm)
    events = resume(graph, {"approved": False})
    assert nodes(events) == ["approval"] and "Not created" in events[-1]["answer"]
    assert asyncio.run(tickets.list_recent()) == []
    state = asyncio.run(graph.aget_state({"configurable": {"thread_id": "r1"}})).values
    assert state["requirement_draft"] == draft and state.get("ticket") is None


@pytest.mark.parametrize("decision", [None, "yes", {"approved": "true"}, {"approved": 1}, {},
                                      {"approved": True, "edits": {"rule_ids": ["OL-01"]}},
                                      {"approved": True, "edits": {"priority": "urgent"}}])
def test_anything_but_a_well_formed_approval_is_a_rejection(graph, fake_lm, tickets, decision):
    make_draft(graph, fake_lm)
    ask_for_ticket(graph, fake_lm)
    events = resume(graph, decision)
    assert "Not created" in events[-1]["answer"] and not of(events, "ticket")
    assert asyncio.run(tickets.list_recent()) == []


def test_edits_at_approval_are_applied_and_marked(graph, fake_lm, tickets):
    make_draft(graph, fake_lm)
    ask_for_ticket(graph, fake_lm)
    events = resume(graph, {"approved": True, "edits": {"priority": "medium", "effective_date": "2026-04-02",
                                                        "acceptance_criteria": ["One", "Two"]}})
    number = of(events, "ticket")[0]["ticket"]["number"]
    detail = asyncio.run(tickets.get_ticket(number))
    assert detail.priority == "medium" and detail.effective_date == "2026-04-02"
    assert detail.acceptance_criteria == ["One", "Two"]
    state = asyncio.run(graph.aget_state({"configurable": {"thread_id": "r1"}})).values
    assert state["requirement_draft"]["edited"] == ["acceptance_criteria", "effective_date", "priority"]
    assert any("edited at approval" in w for w in state["requirement_draft"]["warnings"])
    assert "Edited at approval: acceptance_criteria, priority, effective_date." in events[-1]["notes"]


def test_a_new_message_while_waiting_ends_the_wait_without_a_ticket(graph, fake_lm, tickets):
    make_draft(graph, fake_lm)
    ask_for_ticket(graph, fake_lm)
    fake_lm.script("route", {"intent": "out_of_scope", "countries": [], "date_phrases": [], "search_query": ""})
    events = run(graph, "Actually, never mind. Tell me a joke.")
    assert events[-1]["awaiting_approval"] is False
    snapshot = asyncio.run(graph.aget_state({"configurable": {"thread_id": "r1"}}))
    assert not snapshot.interrupts and asyncio.run(tickets.list_recent()) == []


def test_the_button_needs_no_model_and_a_ticket_needs_a_draft(graph, fake_lm, tickets):
    make_draft(graph, fake_lm)
    calls = len(fake_lm.requests)
    events = ask_for_ticket(graph, fake_lm, message="Create ticket", action="create_ticket")
    assert of(events, "approval") and len(fake_lm.requests) == calls   # no route call for the button
    # no draft in this thread: "create a ticket" becomes a draft request (or a clarifying question)
    fake_lm.script("route", route("create_ticket", countries=()))
    events = run(graph, "Create a ticket", thread="other")
    assert nodes(events) == ["route", "clarify"]
    fake_lm.script("route", route("create_ticket", countries=()))
    events = run(graph, "Create ticket", thread="other2", action="create_ticket")  # a button without a draft
    assert nodes(events) == ["route", "clarify"] and not of(events, "approval")


def test_a_ticket_system_outage_creates_nothing_and_says_so(graph, fake_lm, monkeypatch):
    from copilot.integrations.servicenow import TicketSystemError

    class Down:
        async def create_requirement(self, *args):
            raise TicketSystemError("ServiceNow is not reachable (ConnectError).")
    monkeypatch.setattr("copilot.graph.nodes.requirement.ticket_system", lambda: Down())
    make_draft(graph, fake_lm)
    ask_for_ticket(graph, fake_lm)
    events = resume(graph, {"approved": True})
    assert "could not be created: ServiceNow is not reachable" in events[-1]["answer"]
    assert not of(events, "ticket")


def test_create_ticket_checks_the_approval_itself(graph):
    """Even if something routed to create_ticket without the approval node, the node refuses."""
    from copilot.graph.nodes.requirement import create_ticket

    draft = {"title": "x"}
    for decision in (None, {"approved": False}, {"approved": True, "draft_hash": "other"}):
        state = {"language": "en", "requirement_draft": draft, "approval": decision}
        result = asyncio.run(_call_outside_graph(create_ticket, state))
        assert result["answer"].startswith("Not created")
    assert draft_hash(draft) != "other"


async def _call_outside_graph(node, state):
    from unittest.mock import patch

    with patch("copilot.graph.nodes.common.get_stream_writer", lambda: (lambda event: None)):
        return await node(state)


def test_apply_decision_unit():
    draft = {"title": "Deadline", "country": "OL", "effective_date": "2026-04-01", "user_story": "As ...",
             "acceptance_criteria": ["x"], "rule_ids": [], "doc_refs": ["OL-AM-12 §2"], "priority": "high",
             "as_of": "2026-04-01", "warnings": [], "edited": []}
    assert apply_decision({"approved": True}, draft) == (draft, "")
    assert apply_decision({"approved": True, "edits": {"title": "Deadline"}}, draft) == (draft, "")
    edited, note = apply_decision({"approved": True, "edits": {"title": "New title"}}, draft)
    assert edited["title"] == "New title" and edited["edited"] == ["title"] and note.endswith("title.")
    assert apply_decision({"approved": False, "edits": {"title": "New title"}}, draft) == (None, "")
    rejected, note = apply_decision({"approved": True, "edits": {"title": "x"}}, draft)  # too short
    assert rejected is None and "not valid" in note
