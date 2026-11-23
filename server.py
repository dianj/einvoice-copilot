"""FastAPI app (async). E1: health, the corpus and the rule definitions. Run with: uvicorn server:app"""
import logging
from datetime import date
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException

from copilot import config
from copilot.corpus.loader import corpus
from copilot.rules.definitions import rules

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")

VERSION = "0.1.0"
app = FastAPI(title="E-Invoice Compliance Copilot", version=VERSION)


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
