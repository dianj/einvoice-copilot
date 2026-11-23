"""Run one chat turn and translate the graph's stream into UI events.

Events (each a dict with "event"): node_started, node_finished (ms), sources (passages per date), findings (the
engine's report), table (a comparison), final (answer, citations, dates, notes), error (the run failed; the
checkpoint keeps the last completed step, so the thread stays usable).
"""
import logging
from collections.abc import AsyncIterator

from copilot.graph.prompts import PROMPT_VERSION
from copilot.llm import LLMError

log = logging.getLogger("copilot.graph")

# Fields of one turn. Every new message resets them, so nothing from the previous answer leaks into this one.
TURN_DEFAULTS = {"intent": None, "clarify": "", "countries": [], "date_phrases": [], "search_query": "",
                 "dates": [], "date_source": None, "retrievals": [], "report": None, "rule_passages": [],
                 "explanations": [], "comparison": None, "answer": "", "citations": [], "notes": []}

FINAL_FIELDS = ("intent", "language", "answer", "citations", "dates", "date_source", "notes", "explanations")


def turn_input(message: str, attachment_id: str | None = None, params: dict | None = None) -> dict:
    return {**TURN_DEFAULTS, "user_input": message, "attachment_id": attachment_id, "params": params or {}}


def source_summary(passage: dict) -> dict:
    keys = ("ref", "doc_id", "title", "doc_type", "authority", "valid_from", "valid_to", "heading", "text")
    return {k: passage.get(k) for k in keys}


async def stream_turn(graph, thread_id: str, message: str, attachment_id: str | None = None,
                      params: dict | None = None) -> AsyncIterator[dict]:
    config = {"configurable": {"thread_id": thread_id}}
    try:
        async for mode, chunk in graph.astream(turn_input(message, attachment_id, params), config,
                                               stream_mode=["updates", "custom"]):
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
    except LLMError as exc:
        log.warning("thread %s: %s", thread_id, exc)
        yield {"event": "error", "message": "The language model is not available right now "
                                            f"({exc}). Please try again in a moment."}
        return
    except Exception:
        log.exception("thread %s: the run failed", thread_id)
        yield {"event": "error", "message": "Something went wrong while answering. Please try again."}
        return
    state = (await graph.aget_state(config)).values
    yield {"event": "final", "thread_id": thread_id, "prompt_version": PROMPT_VERSION,
           **{k: state.get(k) for k in FINAL_FIELDS}}
