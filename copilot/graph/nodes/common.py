"""Helpers shared by the nodes: progress events, replies, the reply language and passage dicts."""
import functools
import logging
import re
import time

from langgraph.config import get_stream_writer
from langgraph.errors import GraphInterrupt

from copilot import observability

log = logging.getLogger("copilot.graph")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LATIN = re.compile(r"[A-Za-z]")


def traced(name: str):
    """Report `node_started` / `node_finished` (with milliseconds) on the graph's custom stream, for the UI's
    progress line, and store the node as a span of the current run (tokens, documents, status)."""
    def decorate(fn):
        @functools.wraps(fn)
        async def node(state):
            write = get_stream_writer()
            write({"event": "node_started", "node": name})
            span = observability.begin_span()
            started_at = observability._now()
            start = time.perf_counter()
            status, result, error = "error", None, None
            try:
                result = await fn(state)
                status = "ok"
                return result
            except GraphInterrupt:
                status = "waiting"  # paused for a person (the approval interrupt); resumes in a later request
                raise
            except Exception as exc:
                error = type(exc).__name__
                raise
            finally:
                ms = int((time.perf_counter() - start) * 1000)
                write({"event": "node_finished", "node": name, "ms": ms, "status": status})
                log.info("node %s %s in %d ms", name, status, ms)
                await observability.record_span(name, started_at, ms, status, span, result, error)
        return node
    return decorate


def language(text: str) -> str:
    """Bulgarian when Cyrillic letters outnumber Latin ones (rule ids such as KS-04 stay Latin in any language)."""
    return "bg" if len(CYRILLIC.findall(text)) > len(LATIN.findall(text)) else "en"


def reply(text: str, **fields) -> dict:
    """The state update of a node that ends the turn: the answer, also added to the thread's messages."""
    return {"answer": text, "messages": [{"role": "assistant", "content": text}], **fields}


def passage_dict(item) -> dict:
    """A retrieved Passage or a raw Chunk as a plain dict with its reference ("KS-CL-01 §2")."""
    data = item.model_dump(mode="json", exclude={"test_only", "chunk_no"})
    data["ref"] = item.ref
    data.setdefault("vector_score", None)
    data.setdefault("fused_score", None)
    return data


def unique_passages(groups: list[list[dict]]) -> list[dict]:
    seen, out = set(), []
    for group in groups:
        for p in group:
            if p["chunk_id"] not in seen:
                seen.add(p["chunk_id"])
                out.append(p)
    return out
