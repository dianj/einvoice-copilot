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
BRACKET = re.compile(r"\s?\[([^\[\]]{3,120})\]")
# Any document-like reference, not only known prefixes: an invented "XX-LAW-99 §1" must be caught, not ignored.
REF = re.compile(r"\b([A-Z]{2,5}-(?:[A-Z]+-)?\d{2})\s*§\s*(\d+)")


def check_citations(answer: str, allowed: set[str]) -> tuple[str, list[str], list[str]]:
    """(answer without invalid references, valid refs in order, invalid refs). Brackets that are not citations
    (no "DOC §n" inside) are left alone."""
    valid, invalid = [], []

    def fix(match: re.Match) -> str:
        refs = [f"{doc} §{num}" for doc, num in REF.findall(match.group(1))]
        if not refs:
            return match.group(0)
        kept = [r for r in refs if r in allowed]
        for r in refs:
            (valid if r in allowed else invalid).append(r)
        return f" [{', '.join(kept)}]" if kept else ""

    cleaned = BRACKET.sub(fix, answer)
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
    answer = str(result.data.get("answer", "")).strip()
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
