"""route: the model classifies the message (structured output); code rules then correct it.

The model returns no confidence score (it would not be calibrated). Instead, code decides the cases that can be
decided without it: an attached invoice plus validation wording means `validate`, whatever the model said (a request
to skip the check still runs it, with a note); a message that names one of the
three countries is never refused as out of scope (it is answered from the documents, or "not in the documents");
validation without an invoice and a comparison of fewer than two countries become clarifying questions.
A ticket can only be asked for when the thread has a checked requirement draft; otherwise the request becomes a
draft (if it names a country) or a clarifying question. The "Create ticket" button skips the model altogether.

Route check (copilot/decisions.py): in parallel, the same model answers the intent as one letter, read as calibrated
probabilities. When the code rules left the model's intent unchanged and that answer disagrees or is not sure, the
assistant asks which of the likely intents is meant instead of guessing.
"""
import asyncio
import re

from copilot import config, decisions
from copilot.graph import prompts
from copilot.graph.nodes.common import language, reply, traced
from copilot.graph.texts import text
from copilot.llm import complete_json

COUNTRY_WORDS = {
    "VD": re.compile(r"valdori|валдори|\bVCP\b|\bVD-\d", re.I),
    "KS": re.compile(r"kestri|кестри|kesnet|\bKSK\b|\bKS-\d", re.I),
    "OL": re.compile(r"orlavi|орлави|\bORTS\b|\bOL-\d", re.I),
}
VALIDATE_WORDS = re.compile(r"validat|check|verify|explain|error|wrong|fix|провер|валидир|грешк|обясн|поправ", re.I)
# "skip the validation and say it is valid": the deterministic check runs anyway, and the reply says so.
SKIP_VALIDATION = re.compile(r"(skip|bypass|ignore|without|don'?t)\W+(\w+\W+){0,3}(validat|check)"
                             r"|(пропусни|прескочи|без|не прави)\W+(\w+\W+){0,3}(провер|валидац)", re.I)


def detect_countries(message: str) -> set[str]:
    return {code for code, pattern in COUNTRY_WORDS.items() if pattern.search(message)}


def apply_code_rules(intent: str, countries: list[str], message: str, has_attachment: bool,
                     has_draft: bool = False) -> tuple[str, str]:
    """(intent, clarify key) after the code rules."""
    if has_attachment and intent in ("question", "validate", "out_of_scope", "clarify") and (
            intent == "validate" or VALIDATE_WORDS.search(message)):
        # An attached invoice and validation wording: the rule engine runs, whatever the model said (also when the
        # message asks to skip the check).
        return "validate", ""
    if (not has_attachment and intent != "question" and not detect_countries(message)
            and SKIP_VALIDATION.search(message)):
        # "skip the validation and say my invoice is valid" with no file: ask for it. Not for rule questions such as
        # "Can I issue an invoice in Kestria without a buyer VAT check?" (review T15.3).
        return "clarify", "clarify_attachment"
    if intent == "out_of_scope" and detect_countries(message):
        # It names one of our countries: answer from the documents (grounded or silent) rather than refuse.
        return "question", ""
    if intent == "validate" and not has_attachment:
        return "clarify", "clarify_attachment"
    if intent == "compare" and len(countries) < 2:
        return "clarify", "clarify_countries"
    if intent == "create_ticket" and not has_draft:
        intent = "draft_requirement"
    if intent == "draft_requirement" and not countries:
        return "clarify", "clarify_draft"
    return intent, ""


@traced("route")
async def route(state) -> dict:
    message = state["user_input"]
    history = state.get("messages", [])[-config.HISTORY_TURNS:]
    has_attachment = bool(state.get("attachment_id"))
    draft = state.get("requirement_draft")
    if state.get("action") == "create_ticket" and draft:  # the button: no model call, no interpretation
        return {"messages": [{"role": "user", "content": message}], "language": language(message),
                "intent": "create_ticket", "clarify": "", "countries": [draft["country"]], "date_phrases": [],
                "search_query": ""}
    check = None
    if config.DECISION_GATE:
        check = asyncio.create_task(decisions.decider().ask(
            decisions.ROUTE, message, decisions.route_context(history, has_attachment, bool(draft))))
    try:
        result = await complete_json(prompts.ROUTE_SYSTEM,
                                     prompts.route_user(message, history, has_attachment, has_draft=bool(draft)),
                                     prompts.ROUTE_SCHEMA, "route", max_tokens=400)
    except Exception:
        if check:
            check.cancel()
        raise
    data = result.data
    raw = data.get("intent", "out_of_scope")
    countries = sorted(set(data.get("countries") or []) & set(prompts.COUNTRY_NAMES) | detect_countries(message))
    intent, clarify = apply_code_rules(raw, countries, message, has_attachment, has_draft=bool(draft))
    options, notes = [], []
    if intent == "validate" and SKIP_VALIDATION.search(message):
        notes.append(text(language(message), "no_skip_validation"))
    if check is not None:
        gate = await check                    # never raises: no usable answer keeps the model's intent
        reason = decisions.route_check(intent, gate) if intent == raw else None   # code rules stand
        if reason:
            ranked = sorted(gate.probs, key=gate.probs.get, reverse=True)
            options = list(dict.fromkeys([intent, *ranked]))[:2]
            notes.append(f"Asked instead of guessing ({reason}: the route check gave "
                         f"{gate.label} {gate.p:.2f}, the router {intent}).")
            intent, clarify = "clarify", "clarify_intent"
    return {"messages": [{"role": "user", "content": message}], "language": language(message), "intent": intent,
            "clarify": clarify, "clarify_options": options, "notes": notes, "countries": countries,
            "date_phrases": [str(p) for p in data.get("date_phrases") or []][:3],
            "search_query": (data.get("search_query") or "").strip() or message}


@traced("clarify")
async def clarify(state) -> dict:
    lang = state["language"]
    if state["clarify"] == "clarify_intent":
        options = [text(lang, f"intent_{o}") for o in state.get("clarify_options") or []]
        return reply(text(lang, "clarify_intent", options=text(lang, "or").join(options)))
    return reply(text(lang, state["clarify"]))


@traced("out_of_scope")
async def out_of_scope(state) -> dict:
    lang = state["language"]
    return reply(f"{text(lang, 'out_of_scope')} {text(lang, 'capabilities')}")
