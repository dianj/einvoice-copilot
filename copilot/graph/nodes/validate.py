"""validate_invoice → retrieve_rule_docs → explain_findings: the engine decides, the model explains.

The report comes from the deterministic rule engine. The model gets the report and the rule documents and writes
one explanation per rule id; code checks that the explained ids are exactly the report's (the schema already only
allows those ids) and falls back to the engine's own message for any it left out. A valid invoice or an unreadable
file needs no model at all.
"""
import asyncio
from datetime import date

from copilot.attachments import load
from copilot.graph import prompts
from copilot.graph.nodes.common import language, passage_dict, reply, traced
from copilot.graph.texts import text
from copilot.kb.retriever import Retriever, retriever
from copilot.llm import complete_json
from copilot.rules.engine import validate

PARAM_NAMES = ("country", "transaction_type", "stage", "taxpayer_size")


@traced("validate_invoice")
async def validate_invoice(state) -> dict:
    data = load(state.get("attachment_id") or "")
    if data is None:
        return {"report": None, **reply(text(state["language"], "attachment_missing"))}
    params = {k: v for k, v in (state.get("params") or {}).items() if k in PARAM_NAMES and v}
    report = await asyncio.to_thread(validate, data, **params)
    day = (report.rule_date or date.today()).isoformat()
    return {"report": report.model_dump(mode="json"), "dates": [day], "date_source": "invoice",
            "notes": list(state.get("notes", [])) + list(report.notes)}   # keep route's ("cannot be skipped")


def route_after_validation(state) -> str:
    return "retrieve_rule_docs" if state.get("report") else "end"


@traced("retrieve_rule_docs")
async def retrieve_rule_docs(state) -> dict:
    """The exact sections the findings cite (not a similarity search), in the versions in force on the rule date."""
    report = state["report"]
    refs = list(dict.fromkeys(ref for f in report["findings"] for ref in f["doc_ref"]))
    if not refs:
        return {"rule_passages": []}
    kb = await asyncio.to_thread(retriever)
    day = date.fromisoformat(report["rule_date"])
    passages = [passage_dict(c) for c in kb.chunks.values()
                if c.ref in refs and Retriever.allowed(c, day, None, None, include_test=False)]
    passages.sort(key=lambda p: (refs.index(p["ref"]), p["chunk_id"]))
    return {"rule_passages": passages}


def fallback_explanation(finding: dict) -> dict:
    return {"rule_id": finding["rule_id"], "explanation": finding["message"], "likely_cause": "",
            "fix": finding["fix_hint"], "citation": (finding["doc_ref"] or [""])[0], "source": "engine"}


def merge_explanations(report: dict, model_items: list[dict], allowed_refs: set[str]) -> tuple[list[dict], list[str]]:
    """One explanation per rule id of the report, in its order. Returns (explanations, notes)."""
    first = {}
    for finding in report["findings"]:
        first.setdefault(finding["rule_id"], finding)
    by_id, notes = {}, []
    for item in model_items:
        rule_id = item.get("rule_id")
        if rule_id not in first:
            notes.append(f"The model explained {rule_id}, which is not in the report: dropped.")
        elif rule_id not in by_id:
            by_id[rule_id] = item
    out = []
    for rule_id, finding in first.items():
        item = by_id.get(rule_id)
        if item is None:
            notes.append(f"The model left out {rule_id}: the engine's own message is shown.")
            out.append(fallback_explanation(finding))
            continue
        citation = item.get("citation", "")
        if citation not in allowed_refs:  # not a provided passage: use the section the rule itself cites
            citation = (finding["doc_ref"] or [""])[0]
        out.append({"rule_id": rule_id, "explanation": item.get("explanation", ""),
                    "likely_cause": item.get("likely_cause", ""), "fix": item.get("fix", ""),
                    "citation": citation, "source": "model"})
    return out, notes


def render(lang: str, summary: str, explanations: list[dict]) -> str:
    lines = [summary.strip()] if summary.strip() else []
    for e in explanations:
        cite = f" [{e['citation']}]" if e["citation"] else ""
        cause = f" {text(lang, 'cause')}: {e['likely_cause']}" if e["likely_cause"] else ""
        lines.append(f"• {e['rule_id']}: {e['explanation']}{cause} {text(lang, 'fix')}: {e['fix']}{cite}")
    return "\n".join(lines)


@traced("explain_findings")
async def explain_findings(state) -> dict:
    report = state["report"]
    lang = state.get("language") or language(state["user_input"])
    findings = report["findings"]
    if not findings:
        sets = ", ".join(sorted({rule_id.split("-")[0] for rule_id in report["rules_checked"]}))
        return reply(text(lang, "valid", count=len(report["rules_checked"]), sets=sets, country=report["country"],
                          transaction_type=report["transaction_type"], date=report["rule_date"]),
                     explanations=[], citations=[])
    if findings[0]["rule_id"] == "XML-00":
        return reply(text(lang, "unreadable", reason=findings[0]["message"], fix=findings[0]["fix_hint"]),
                     explanations=[], citations=[])
    passages = state.get("rule_passages", [])
    refs = list(dict.fromkeys(p["ref"] for p in passages))
    rule_ids = list(dict.fromkeys(f["rule_id"] for f in findings))
    result = await complete_json(prompts.EXPLAIN_SYSTEM.format(language=prompts.LANGUAGE_NAMES[lang]),
                                 prompts.explain_user(report, passages), prompts.explain_schema(rule_ids, refs),
                                 "explain_findings", max_tokens=2500)
    explanations, notes = merge_explanations(report, result.data.get("explanations") or [], set(refs))
    citations = list(dict.fromkeys(e["citation"] for e in explanations if e["citation"]))
    return reply(render(lang, str(result.data.get("summary", "")), explanations), explanations=explanations,
                 citations=citations, notes=list(state.get("notes", [])) + notes)
