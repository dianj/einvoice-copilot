"""retrieve + answer_grounded: "grounded or silent".

One search per date (the version filter differs per date). The model answers only from those passages, and code
checks the result: every citation must name a retrieved passage (others are removed and reported), and an answer
that claims to be in the documents but cites nothing valid is replaced by an honest "could not answer".
"""
import asyncio
import re
from datetime import date

from copilot.graph import prompts
from copilot.graph.nodes.common import passage_dict, reply, traced, unique_passages
from copilot.graph.texts import text
from copilot.kb.retriever import retriever
from copilot.llm import complete_json

VAGUE_WORDS = 4   # a message this short gets the answer plus the other things the assistant can do
# The model sometimes writes a schema field into the text ("in_documents: false. Предоставените документи ...").
FIELD_ECHO = re.compile(r"^\s*in_documents\s*:\s*(true|false)\s*[.,;:]?\s*", re.I)
# Any document-like reference, not only known prefixes: an invented "XX-LAW-99 §1" must be caught, not ignored.
REF = re.compile(r"\b([A-Z]{2,5}-(?:[A-Z]+-)?\d{2})\s*§\s*(\d+)")
_REF = r"\b[A-Z]{2,5}-(?:[A-Z]+-)?\d{2}\s*§\s*\d+"
# One pass over the answer, so references come out in reading order: a [bracket] (citations or an ordinary
# remark), parentheses holding only references "(VD-AM-03 §2; OL-TS-01 §4)", or a bare reference in a sentence.
CITATION = re.compile(r"\s?\[(?P<bracket>[^\[\]]{3,120})\]"
                      rf"|\s?\((?P<paren>\s*{_REF}(?:\s*[,;]\s*{_REF})*\s*)\)"
                      rf"|(?P<bare>{_REF})")


def _tidy(text: str) -> str:
    """Close the gap a removed bare reference leaves ("Per , invoices" -> "Per, invoices")."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    return re.sub(r"(^|[.!?]\s)\s*,\s*", r"\1", text).strip()


def check_citations(answer: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    """(answer without invalid references, valid refs in order, invalid refs). Every reference counts, wherever it
    stands: in [brackets], in (parentheses) or bare in a sentence ("Per VD-LAW-77 §9, ..."). An invalid one is
    removed, and a bracket or parenthesis left empty goes with it. Brackets that are not citations (no "DOC §n"
    inside) are left alone."""
    valid, invalid = [], []
    removed_bare = False

    def fix(match: re.Match) -> str:
        nonlocal removed_bare
        inside = match.group("bracket") or match.group("paren") or match.group("bare")
        refs = [f"{doc} §{num}" for doc, num in REF.findall(inside)]
        if not refs:
            return match.group(0)
        for r in refs:
            (valid if r in allowed else invalid).append(r)
        kept = [r for r in refs if r in allowed]
        if match.group("bare") is not None:
            removed_bare = removed_bare or not kept
            return match.group(0) if kept else ""
        if not kept:
            return ""
        open_, close = ("[", "]") if match.group("bracket") is not None else ("(", ")")
        return f" {open_}{', '.join(kept)}{close}"

    cleaned = CITATION.sub(fix, answer)
    if removed_bare:
        cleaned = _tidy(cleaned)
    return cleaned, list(dict.fromkeys(valid)), list(dict.fromkeys(invalid))


@traced("retrieve")
async def retrieve(state) -> dict:
    kb = await asyncio.to_thread(retriever)  # builds the index on first use
    countries = set(state.get("countries") or []) or None
    retrievals = []
    for day in state["dates"]:
        result = await kb.search(state["search_query"], as_of=date.fromisoformat(day), countries=countries, k=6)
        retrievals.append({"as_of": day, "answerable": result.answerable,
                           "top_vector_score": result.top_vector_score,
                           "passages": [passage_dict(p) for p in result.passages]})
    return {"retrievals": retrievals}


@traced("answer_grounded")
async def answer_grounded(state) -> dict:
    lang = state["language"]
    retrievals = state.get("retrievals", [])
    dates = ", ".join(state["dates"])
    if not any(r["answerable"] for r in retrievals):  # the similarity gate: nothing close enough to the question
        return reply(text(lang, "not_in_documents", dates=dates), citations=[])
    passages = unique_passages([r["passages"] for r in retrievals])
    result = await complete_json(prompts.ANSWER_SYSTEM.format(language=prompts.LANGUAGE_NAMES[lang]),
                                 prompts.answer_user(state["user_input"], state["dates"], passages),
                                 prompts.ANSWER_SCHEMA, "grounded_answer")
    answer = FIELD_ECHO.sub("", str(result.data.get("answer", ""))).strip()
    cleaned, valid, invalid = check_citations(answer, {p["ref"] for p in passages})
    notes = list(state.get("notes", []))
    if invalid:
        notes.append(f"Removed citations that do not match a retrieved passage: {', '.join(invalid)}.")
    if not result.data.get("in_documents"):
        return reply(cleaned or text(lang, "not_in_documents", dates=dates), citations=[], notes=notes)
    if not valid:
        notes.append("The model's answer cited no retrieved passage, so it was not shown.")
        return reply(text(lang, "ungrounded"), citations=[], notes=notes)
    if len(state["user_input"].split()) <= VAGUE_WORDS:   # "What about Valdoria?": also say what else is possible
        cleaned = f"{cleaned}\n\n{text(lang, 'more_options')}"
    return reply(cleaned, citations=valid, notes=notes)
