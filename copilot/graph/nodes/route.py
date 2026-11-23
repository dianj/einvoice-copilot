"""route: the model classifies the message (structured output); code rules then correct it.

The model returns no confidence score (it would not be calibrated). Instead, code decides the cases that can be
decided without it: an attached invoice plus validation wording means `validate`; a message that names one of the
three countries is never refused as out of scope (it is answered from the documents, or "not in the documents");
validation without an invoice and a comparison of fewer than two countries become clarifying questions.
A ticket can only be asked for when the thread has a checked requirement draft; otherwise the request becomes a
draft (if it names a country) or a clarifying question. The "Create ticket" button skips the model altogether.
"""
import re

from copilot import config
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


def detect_countries(message: str) -> set[str]:
    return {code for code, pattern in COUNTRY_WORDS.items() if pattern.search(message)}


def apply_code_rules(intent: str, countries: list[str], message: str, has_attachment: bool,
                     has_draft: bool = False) -> tuple[str, str]:
    """(intent, clarify key) after the code rules."""
    if has_attachment and intent in ("question", "validate") and (intent == "validate" or
                                                                 VALIDATE_WORDS.search(message)):
        return "validate", ""
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
    result = await complete_json(prompts.ROUTE_SYSTEM,
                                 prompts.route_user(message, history, has_attachment, has_draft=bool(draft)),
                                 prompts.ROUTE_SCHEMA, "route", max_tokens=400)
    data = result.data
    countries = sorted(set(data.get("countries") or []) & set(prompts.COUNTRY_NAMES) | detect_countries(message))
    intent, clarify = apply_code_rules(data.get("intent", "out_of_scope"), countries, message, has_attachment,
                                       has_draft=bool(draft))
    return {"messages": [{"role": "user", "content": message}], "language": language(message), "intent": intent,
            "clarify": clarify, "countries": countries,
            "date_phrases": [str(p) for p in data.get("date_phrases") or []][:3],
            "search_query": (data.get("search_query") or "").strip() or message}


@traced("clarify")
async def clarify(state) -> dict:
    return reply(text(state["language"], state["clarify"]))


@traced("out_of_scope")
async def out_of_scope(state) -> dict:
    lang = state["language"]
    return reply(f"{text(lang, 'out_of_scope')} {text(lang, 'capabilities')}")
