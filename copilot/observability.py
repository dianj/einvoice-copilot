"""Runs and spans (ARCHITECTURE.md §11): what each request did, node by node, stored in SQLite (`APP_DB`).

A run is one request to the graph (a message, a button press or an approval). `start_run` sets the run id in a
context variable, so every node span (`record_span`, called by the `traced` decorator) and every LLM call
(`add_tokens`, called by `copilot.llm`) inside that request lands in the same run without the nodes passing ids
around. Own spans instead of OpenTelemetry: one table, no collector; OTel would be the production step.
"""
import contextvars
import json
import math
import time
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import aiosqlite

from copilot import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,              -- message | approval
    started_at TEXT NOT NULL,
    ms INTEGER,
    status TEXT NOT NULL,            -- running | ok | waiting | failed | cancelled | interrupted
    intent TEXT,
    language TEXT,
    model TEXT NOT NULL,
    prompt_version TEXT,
    abstained INTEGER,               -- a question answered with "not in the documents"
    findings_json TEXT,              -- the engine's rule ids, for a validation
    approved INTEGER,                -- the decision at the approval card, when there was one
    ticket TEXT,                     -- the ticket number created or found
    final_json TEXT                  -- the final event, for GET /api/runs/{id}
);
CREATE TABLE IF NOT EXISTS spans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    node TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ms INTEGER NOT NULL,
    status TEXT NOT NULL,            -- ok | waiting | error
    tokens_in INTEGER,
    tokens_out INTEGER,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    doc_ids_json TEXT,
    gates_json TEXT,                 -- decision-gate questions asked by this node (question, answer, p, action, ms)
    error TEXT
);
CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id);
"""

current_run: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_run", default=None)
current_span: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_span", default=None)


_ready: set[str] = set()   # databases whose schema is in place (created once per process, not on every write)


async def _db() -> aiosqlite.Connection:
    config.APP_DB.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(config.APP_DB)
    db.row_factory = aiosqlite.Row
    if str(config.APP_DB) not in _ready:
        await db.executescript(SCHEMA)
        async with db.execute("PRAGMA table_info(spans)") as cur:
            columns = {row["name"] for row in await cur.fetchall()}
        if "gates_json" not in columns:               # a database from before the gates were traced
            await db.execute("ALTER TABLE spans ADD COLUMN gates_json TEXT")
            await db.commit()
        _ready.add(str(config.APP_DB))
    return db


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


async def start_run(thread_id: str, kind: str, prompt_version: str) -> str:
    run_id = uuid.uuid4().hex
    db = await _db()
    try:
        await db.execute("INSERT INTO runs (run_id, thread_id, kind, started_at, status, model, prompt_version) "
                         "VALUES (?, ?, ?, ?, 'running', ?, ?)",
                         (run_id, thread_id, kind, _now(), config.LLM_MODEL, prompt_version))
        await db.commit()
    finally:
        await db.close()
    current_run.set(run_id)
    return run_id


async def mark_stale_runs(older_than_minutes: int = 10) -> int:
    """At start-up: runs still `running` after this long were cut off by a crash or a restart -> `interrupted`.
    A recent one is left alone (another worker may still be answering it)."""
    cutoff = (datetime.now(UTC) - timedelta(minutes=older_than_minutes)).isoformat(timespec="milliseconds")
    db = await _db()
    try:
        cur = await db.execute("UPDATE runs SET status = 'interrupted' WHERE status = 'running' AND started_at < ?",
                               (cutoff,))
        await db.commit()
        return cur.rowcount
    finally:
        await db.close()


async def finish_run(run_id: str, started: float, status: str, final: dict | None = None, state: dict | None = None):
    state = state or {}
    final = final or {}
    report = state.get("report") or {}
    approval = state.get("approval")
    abstained = None
    if state.get("intent") == "question":
        abstained = int(not final.get("citations"))
    await _execute(
        "UPDATE runs SET ms = ?, status = ?, intent = ?, language = ?, abstained = ?, findings_json = ?, approved = ?, "
        "ticket = ?, final_json = ? WHERE run_id = ?",
        (int((time.perf_counter() - started) * 1000), status, state.get("intent"), state.get("language"), abstained,
         json.dumps([f["rule_id"] for f in report.get("findings", [])]) if report else None,
         None if not approval else int(bool(approval.get("approved"))),
         (state.get("ticket") or {}).get("number") if approval and approval.get("approved") else None,
         json.dumps(final, ensure_ascii=False) if final else None, run_id))


async def _execute(sql: str, params: tuple):
    db = await _db()
    try:
        await db.execute(sql, params)
        await db.commit()
    finally:
        await db.close()


def begin_span() -> dict:
    """Called by a node when it starts: a fresh counter for this node's LLM calls."""
    span = {"tokens_in": 0, "tokens_out": 0, "llm_calls": 0, "gates": []}
    current_span.set(span)
    return span


def add_tokens(tokens_in: int | None, tokens_out: int | None):
    """Called after every LLM call: adds its usage to the span of the node that made it."""
    span = current_span.get()
    if span is not None:
        span["llm_calls"] += 1
        span["tokens_in"] += tokens_in or 0
        span["tokens_out"] += tokens_out or 0


def add_gate(record: dict):
    """Called for every decision-gate question (copilot.decisions.trace): it is a model call of the node that asked.
    Its tokens are not known here (the gate module keeps its own HTTP client), so only the call is counted."""
    span = current_span.get()
    if span is not None:
        span["llm_calls"] += 1
        span["gates"].append(record)


def doc_ids(result: dict | None) -> list[str]:
    """The documents a node retrieved or cited, from its state update."""
    if not isinstance(result, dict):
        return []
    ids = [p.get("doc_id") for r in result.get("retrievals") or [] for p in r.get("passages", [])]
    ids += [p.get("doc_id") for p in result.get("rule_passages") or []]
    ids += [c.split(" ")[0] for c in result.get("citations") or []]
    return list(dict.fromkeys(i for i in ids if i))


async def record_span(node: str, started_at: str, ms: int, status: str, span: dict, result: dict | None,
                      error: str | None):
    run_id = current_run.get()
    if run_id is None:            # a node run outside a request (tests that call the graph directly)
        return
    await _execute(
        "INSERT INTO spans (run_id, node, started_at, ms, status, tokens_in, tokens_out, llm_calls, doc_ids_json, "
        "gates_json, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, node, started_at, ms, status, span["tokens_in"] or None, span["tokens_out"] or None,
         span["llm_calls"], json.dumps(doc_ids(result)), json.dumps(span.get("gates") or []), error))


async def get_run(run_id: str) -> dict | None:
    db = await _db()
    try:
        async with db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        async with db.execute("SELECT * FROM spans WHERE run_id = ? ORDER BY id", (run_id,)) as cur:
            spans = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    run = dict(row)
    run["final"] = json.loads(run.pop("final_json") or "null")
    run["findings"] = json.loads(run.pop("findings_json") or "null")
    for span in spans:
        span["doc_ids"] = json.loads(span.pop("doc_ids_json") or "[]")
        span["gates"] = json.loads(span.pop("gates_json") or "[]")
    run["spans"] = spans
    return run


def percentile(values: list[int], p: int) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(math.ceil(p / 100 * len(ordered)) - 1, 0)]


async def metrics() -> dict:
    db = await _db()
    try:
        async with db.execute("SELECT * FROM runs WHERE status != 'running'") as cur:
            runs = [dict(r) for r in await cur.fetchall()]
        async with db.execute("SELECT node, ms, status, tokens_in, tokens_out, gates_json FROM spans") as cur:
            spans = [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()
    per_node: dict[str, list[int]] = defaultdict(list)
    for span in spans:
        if span["status"] != "waiting":
            per_node[span["node"]].append(span["ms"])
    questions = [r for r in runs if r["intent"] == "question" and r["abstained"] is not None]
    decisions = [r["approved"] for r in runs if r["approved"] is not None]
    findings = Counter(rule for r in runs for rule in json.loads(r["findings_json"] or "[]"))
    gate_actions: dict[str, Counter] = defaultdict(Counter)
    for span in spans:
        for gate in json.loads(span["gates_json"] or "[]"):
            gate_actions[gate["question"]][gate["action"]] += 1
    end_to_end = [r["ms"] for r in runs if r["ms"] is not None and r["status"] in ("ok", "waiting")]
    return {
        "runs": len(runs),
        "runs_per_intent": dict(Counter(r["intent"] or "none" for r in runs).most_common()),
        "failed_runs": sum(r["status"] == "failed" for r in runs),
        "node_errors": sum(s["status"] == "error" for s in spans),
        "latency_ms": {
            "end_to_end": {"p50": percentile(end_to_end, 50), "p95": percentile(end_to_end, 95), "n": len(end_to_end)},
            "nodes": {node: {"p50": percentile(v, 50), "p95": percentile(v, 95), "n": len(v)}
                      for node, v in sorted(per_node.items())}},
        "tokens": {"in": sum(s["tokens_in"] or 0 for s in spans), "out": sum(s["tokens_out"] or 0 for s in spans)},
        "abstention_rate": round(sum(r["abstained"] for r in questions) / len(questions), 3) if questions else None,
        "findings_per_rule": dict(findings.most_common()),
        "tickets_created": len({r["ticket"] for r in runs if r["ticket"]}),
        "approvals": {"approved": sum(1 for d in decisions if d), "rejected": sum(1 for d in decisions if not d)},
        "gate_actions": {question: dict(actions) for question, actions in sorted(gate_actions.items())},
    }
