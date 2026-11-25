"""FastAPI app (async): the assistant (LangGraph, streamed), ticket approval, tickets, health, corpus, rules,
validation and samples.

Run with: uvicorn server:app
"""
import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from copilot import attachments, config, observability
from copilot.corpus.loader import corpus
from copilot.graph.build import build_graph
from copilot.graph.run import pending_approval, stream_resume, stream_turn
from copilot.integrations.servicenow import TicketSystemError, ticket_system
from copilot.integrations.servicenow.models import DraftEdits, TicketDetail, TicketSummary
from copilot.rules.definitions import rules
from copilot.rules.engine import Country, Stage, TaxpayerSize, TransactionType, ValidationReport, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")

VERSION = "0.4.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The graph with a persistent SQLite checkpointer: threads survive a restart. Runs a restart cut off are marked
    `interrupted`."""
    if stale := await observability.mark_stale_runs():
        log.warning("%d run(s) left running by an earlier process marked interrupted", stale)
    config.CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(config.CHECKPOINT_DB)) as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield


app = FastAPI(title="E-Invoice Compliance Copilot", version=VERSION, lifespan=lifespan)
thread_locks: dict[str, asyncio.Lock] = {}


async def llm_reachable() -> bool:
    """A quick look at the model list; the health check must not hang when LM Studio is down."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            response = await client.get(f"{config.LLM_BASE_URL.rstrip('/')}/models")
        return response.status_code == 200
    except httpx.HTTPError:
        return False


@app.get("/api/health")
async def health():
    docs, rule_set = corpus(), rules()
    return {"status": "ok", "version": VERSION, "llm": {"base_url": config.LLM_BASE_URL,
                                                         "reachable": await llm_reachable()},
            "corpus": {"documents": len(docs)}, "rules": {"count": len(rule_set.all)},
            "tickets": {"backend": config.SN_BACKEND},
            "today": config.today().isoformat()}


@app.get("/api/corpus")
async def list_corpus():
    return {"documents": [{"doc_id": d.doc_id, "title": d.title, "country": d.country, "doc_type": d.doc_type,
                           "version": d.version, "published": d.published, "valid_from": d.valid_from,
                           "valid_to": d.valid_to, "authority": d.authority} for d in corpus()]}


@app.get("/api/corpus/{doc_id}")
async def get_document(doc_id: str):
    doc = next((d for d in corpus() if d.doc_id == doc_id.upper()), None)
    if doc is None:
        raise HTTPException(404, f"Unknown document '{doc_id}'.")
    return doc.model_dump(exclude={"body"})


@app.get("/api/rules")
async def list_rules(country: Literal["VD", "KS", "OL"] | None = None,
                     transaction_type: Literal["B2B", "B2G", "B2C"] = "B2B",
                     as_of: date | None = None, stage: Literal["pre_clearance", "cleared"] = "pre_clearance"):
    """All rule definitions, or, with a country, the rules that apply to such an invoice on that date."""
    rule_set = rules()
    selected = (rule_set.applicable(country, transaction_type, as_of or config.today(), stage) if country
                else rule_set.all)
    return {"rules": [r.model_dump() for r in selected],
            "code_lists": {name: rule_set.code_list(name, country or "CORE")
                           for name in rule_set.sets["CORE"].code_lists}}


@app.post("/api/validate", response_model=ValidationReport)
async def validate_invoice(request: Request, country: Country | None = None,
                           transaction_type: TransactionType | None = None, stage: Stage = "pre_clearance",
                           taxpayer_size: TaxpayerSize = "unknown"):
    """Validate the UBL invoice in the request body (no LLM). Parameters left out are worked out from the invoice."""
    data = await request.body()
    if len(data) > config.MAX_UPLOAD_KB * 1024:
        raise HTTPException(413, f"The invoice is larger than {config.MAX_UPLOAD_KB} KB.")
    return validate(data, country=country, transaction_type=transaction_type, stage=stage,
                    taxpayer_size=taxpayer_size)


# --- the assistant -------------------------------------------------------------------------------------------

@app.post("/api/attachments")
async def upload_attachment(request: Request):
    """Store an invoice (raw XML body) for the chat. It is parsed safely only when the assistant validates it."""
    try:
        attachment_id = attachments.save(await request.body())
    except attachments.AttachmentError as exc:
        raise HTTPException(413 if "larger" in str(exc) else 422, str(exc)) from None
    return {"attachment_id": attachment_id}


class ValidationParams(BaseModel):
    country: Country | None = None
    transaction_type: TransactionType | None = None
    stage: Stage | None = None
    taxpayer_size: TaxpayerSize | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    attachment_id: str | None = Field(None, pattern=r"^[0-9a-f]{32}$")
    params: ValidationParams = ValidationParams()
    action: Literal["create_ticket"] | None = None   # the Create ticket button (code decides, the model is not asked)


class ApprovalRequest(BaseModel):
    interrupt_id: str = Field(min_length=1, max_length=64)
    approved: bool
    edits: DraftEdits = DraftEdits()


def sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


async def thread_lock(thread_id: str) -> asyncio.Lock:
    """One run per thread at a time: two runs on the same thread would interleave their checkpoints."""
    lock = thread_locks.setdefault(thread_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "This conversation is still answering the previous message.")
    await lock.acquire()
    return lock


def stream_events(thread_id: str, lock: asyncio.Lock, source) -> StreamingResponse:
    async def events():
        try:
            yield sse({"event": "thread", "thread_id": thread_id})
            async for event in source:
                yield sse(event)
        finally:
            lock.release()
            thread_locks.pop(thread_id, None)  # no await in between: nothing can be waiting on it

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    """Run the graph for one message and stream its progress as server-sent events (read with fetch: POST).
    A second message while the first is running gets 409. A message while a draft waits for approval ends that
    wait without a ticket."""
    graph = request.app.state.graph
    thread_id = body.thread_id or uuid.uuid4().hex
    lock = await thread_lock(thread_id)
    return stream_events(thread_id, lock, stream_turn(graph, thread_id, body.message, body.attachment_id,
                                                      body.params.model_dump(exclude_none=True), body.action))


@app.post("/api/threads/{thread_id}/approval")
async def answer_approval(thread_id: str, body: ApprovalRequest, request: Request):
    """Approve (optionally with edits) or reject the requirement draft the thread is waiting on. The only way a
    ticket gets created. The interrupt id must be the open one: a stale card (the thread moved on) gets 409."""
    graph = request.app.state.graph
    lock = await thread_lock(thread_id)
    try:
        waiting = pending_approval(await graph.aget_state({"configurable": {"thread_id": thread_id}}))
        if waiting is None or waiting["interrupt_id"] != body.interrupt_id:
            raise HTTPException(409, "This draft is no longer waiting for approval. Ask for the ticket again.")
    except BaseException:
        lock.release()
        thread_locks.pop(thread_id, None)
        raise
    decision = {"approved": body.approved, "edits": body.edits.model_dump(mode="json", exclude_none=True)}
    return stream_events(thread_id, lock, stream_resume(graph, thread_id, decision))


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request):
    state = await request.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})
    if not state.values:
        raise HTTPException(404, f"Unknown thread '{thread_id}'.")
    return {"thread_id": thread_id, "messages": state.values.get("messages", []),
            "requirement_draft": state.values.get("requirement_draft"), "ticket": state.values.get("ticket"),
            "pending_approval": pending_approval(state)}


# --- observability ----------------------------------------------------------------------------------------------

@app.get("/api/runs/{run_id}")
async def get_run(run_id: str = Path(pattern=r"^[0-9a-f]{32}$")):
    """A stored run: status, intent, timing, the final result and its spans (ARCHITECTURE.md §11)."""
    run = await observability.get_run(run_id)
    if run is None:
        raise HTTPException(404, f"Unknown run '{run_id}'.")
    return run


@app.get("/api/runs/{run_id}/trace")
async def get_trace(run_id: str = Path(pattern=r"^[0-9a-f]{32}$")):
    """The graph path of a run, node by node, with timings, tokens and the documents each node used."""
    run = await get_run(run_id)
    return {"run_id": run_id, "status": run["status"], "ms": run["ms"], "model": run["model"], "spans": run["spans"]}


@app.get("/api/metrics")
async def get_metrics():
    return await observability.metrics()


# --- tickets ----------------------------------------------------------------------------------------------------

@app.get("/api/tickets", response_model=list[TicketSummary])
async def list_tickets(limit: int = Query(20, ge=1, le=100)):
    try:
        return await ticket_system().list_recent(limit)
    except TicketSystemError as exc:
        raise HTTPException(503, str(exc)) from None


@app.get("/api/tickets/{number}", response_model=TicketDetail)
async def get_ticket(number: str):
    try:
        ticket = await ticket_system().get_ticket(number)
    except TicketSystemError as exc:
        raise HTTPException(503, str(exc)) from None
    if ticket is None:
        raise HTTPException(404, f"Unknown ticket '{number}'.")
    return ticket


# --- samples ----------------------------------------------------------------------------------------------------

def sample_list() -> dict[str, dict]:
    found = {}
    for path in sorted(config.SAMPLES_DIR.glob("*.expected.json")):
        found[path.name.removesuffix(".expected.json")] = json.loads(path.read_text(encoding="utf-8"))
    return found


@app.get("/api/samples")
async def list_samples():
    return {"samples": [{"name": name, **meta} for name, meta in sample_list().items()]}


@app.get("/api/samples/{name}")
async def get_sample(name: str):
    if name not in sample_list():  # only known names, so no path tricks
        raise HTTPException(404, f"Unknown sample '{name}'.")
    return Response((config.SAMPLES_DIR / f"{name}.xml").read_bytes(), media_type="application/xml")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(config.BASE_DIR / "index.html")
