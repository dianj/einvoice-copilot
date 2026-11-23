"""FastAPI app (async): health, corpus, rule definitions, validation and the sample invoices.

Run with: uvicorn server:app
"""
import json
import logging
from datetime import date
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from copilot import config
from copilot.corpus.loader import corpus
from copilot.rules.definitions import rules
from copilot.rules.engine import Country, Stage, TaxpayerSize, TransactionType, ValidationReport, validate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("copilot")

VERSION = "0.2.0"
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
