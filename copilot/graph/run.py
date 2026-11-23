"""Run one chat turn and translate the graph's stream into UI events.

Events (each a dict with "event"): node_started, node_finished (ms), sources (passages per date), findings (the
engine's report), table (a comparison), draft (a checked requirement draft), approval (the graph waits for a person:
the draft and the interrupt id to answer with), ticket (created or found), final (answer, citations, dates, notes),
error (the run failed; the checkpoint keeps the last completed step, so the thread stays usable).
"""
import logging
from collections.abc import AsyncIterator

from langgraph.types import Command

from copilot.graph.prompts import PROMPT_VERSION
from copilot.graph.texts import text
from copilot.llm import LLMError

log = logging.getLogger("copilot.graph")

# Fields of one turn. Every new message resets them, so nothing from the previous answer leaks into this one.
TURN_DEFAULTS = {"intent": None, "clarify": "", "countries": [], "date_phrases": [], "search_query": "",
                 "dates": [], "date_source": None, "retrievals": [], "report": None, "rule_passages": [],
                 "explanations": [], "comparison": None, "approval": None, "answer": "", "citations": [],
                 "notes": []}

FINAL_FIELDS = ("intent", "language", "answer", "citations", "dates", "date_source", "notes", "explanations")


def turn_input(message: str, attachment_id: str | None = None, params: dict | None = None,
               action: str | None = None) -> dict:
    return {**TURN_DEFAULTS, "user_input": message, "attachment_id": attachment_id, "params": params or {},
            "action": action}


def source_summary(passage: dict) -> dict:
    keys = ("ref", "doc_id", "title", "doc_type", "authority", "valid_from", "valid_to", "heading", "text")
    return {k: passage.get(k) for k in keys}


def pending_approval(snapshot) -> dict | None:
    """The open approval interrupt of a thread (its id and the draft), or None."""
    for item in snapshot.interrupts or ():
        if isinstance(item.value, dict) and item.value.get("kind") == "ticket_approval":
            return {"interrupt_id": item.id, **item.value}
    return None


async def stream_turn(graph, thread_id: str, message: str, attachment_id: str | None = None,
                      params: dict | None = None, action: str | None = None) -> AsyncIterator[dict]:
    """A new message. If the thread was waiting for an approval, that wait ends here: the draft was not approved
    (nothing is created), and the new message is handled from the start."""
    async for event in _stream(graph, thread_id, turn_input(message, attachment_id, params, action)):
        yield event


async def stream_resume(graph, thread_id: str, decision: dict) -> AsyncIterator[dict]:
    """Answer the approval interrupt (`decision` = {"approved": bool, "edits": {...}}, checked by the caller and
    again by the approval node). Anything else counts as a rejection (an empty resume value would not resume)."""
    if not isinstance(decision, dict) or not decision:
        decision = {"approved": False}
    async for event in _stream(graph, thread_id, Command(resume=decision)):
        yield event


async def _stream(graph, thread_id: str, graph_input) -> AsyncIterator[dict]:
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for mode, chunk in graph.astream(graph_input, config, stream_mode=["updates", "custom"]):
            if mode == "custom":
                yield chunk
                continue
            for node, update in chunk.items():
                update = update or {}
                if node == "retrieve":
                    yield {"event": "sources", "retrievals": [
                        {"as_of": r["as_of"], "answerable": r["answerable"],
                         "passages": [source_summary(p) for p in r["passages"]]} for r in update["retrievals"]]}
                elif node == "validate_invoice" and update.get("report"):
                    yield {"event": "findings", "report": update["report"]}
                elif node == "compare_countries":
                    yield {"event": "table", "comparison": update["comparison"]}
                elif node == "draft_requirement" and update.get("requirement_draft"):
                    yield {"event": "draft", "draft": update["requirement_draft"]}
                elif node == "create_ticket" and update.get("ticket"):
                    yield {"event": "ticket", "ticket": update["ticket"]}
    except LLMError as exc:
        log.warning("thread %s: %s", thread_id, exc)
        yield {"event": "error", "message": "The language model is not available right now "
                                            f"({exc}). Please try again in a moment."}
        return
    except Exception:
        log.exception("thread %s: the run failed", thread_id)
        yield {"event": "error", "message": "Something went wrong while answering. Please try again."}
        return
    snapshot = await graph.aget_state(config)
    state = snapshot.values
    waiting = pending_approval(snapshot)
    if waiting:
        yield {"event": "approval", **waiting}
        yield {"event": "final", "thread_id": thread_id, "prompt_version": PROMPT_VERSION, "awaiting_approval": True,
               **{k: state.get(k) for k in FINAL_FIELDS},
               "answer": text(state.get("language", "en"), "approval_needed"), "citations": []}
        return
    yield {"event": "final", "thread_id": thread_id, "prompt_version": PROMPT_VERSION, "awaiting_approval": False,
           **{k: state.get(k) for k in FINAL_FIELDS}}
