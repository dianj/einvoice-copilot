"""FastAPI app (async): the assistant (LangGraph, streamed), health, corpus, rules, validation and samples.

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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field

from copilot import attachments, config
from copilot.corpus.loader import corpus
from copilot.graph.build import build_graph
from copilot.graph.run import stream_turn
from copilot.rules.definitions import rules
from copilot.rules.engine import Country, Stage, TaxpayerSize, TransactionType, ValidationReport, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")

VERSION = "0.3.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """The graph with a persistent SQLite checkpointer: threads survive a restart."""
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


def sse(event: dict) -> str:
    return f"event: {event['event']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request):
    """Run the graph for one message and stream its progress as server-sent events (read with fetch: POST).

    One run per thread at a time: a second message while the first is running gets 409, because two runs on the
    same thread would interleave their checkpoints."""
    graph = request.app.state.graph
    thread_id = body.thread_id or uuid.uuid4().hex
    lock = thread_locks.setdefault(thread_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(409, "This conversation is still answering the previous message.")
    await lock.acquire()

    async def events():
        try:
            yield sse({"event": "thread", "thread_id": thread_id})
            async for event in stream_turn(graph, thread_id, body.message, body.attachment_id,
                                           body.params.model_dump(exclude_none=True)):
                yield sse(event)
        finally:
            lock.release()
            thread_locks.pop(thread_id, None)  # no await in between: nothing can be waiting on it

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request):
    state = await request.app.state.graph.aget_state({"configurable": {"thread_id": thread_id}})
    if not state.values:
        raise HTTPException(404, f"Unknown thread '{thread_id}'.")
    return {"thread_id": thread_id, "messages": state.values.get("messages", [])}


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
