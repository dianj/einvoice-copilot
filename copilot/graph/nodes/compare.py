"""compare_countries: one cited column per country, merged into a table by code.

For each country and aspect, the three best passages of that country's documents (in force on the date); then one
model call per country fills its column (fits a 16k context). A cell counts only with a citation of a passage that
was provided for that country; anything else becomes "Not specified in the documents."
"""
import asyncio
from datetime import date

from copilot.graph import prompts
from copilot.graph.nodes.common import passage_dict, reply, traced, unique_passages
from copilot.graph.texts import text
from copilot.kb.retriever import retriever
from copilot.llm import complete_json

PER_ASPECT = 3


async def country_passages(kb, country: str, as_of: date) -> list[dict]:
    groups = []
    for _, query in prompts.ASPECTS.values():
        result = await kb.search(f"{prompts.COUNTRY_NAMES[country]} {query}", as_of=as_of, countries={country}, k=6)
        # the country's own documents only: the common model and the unofficial overview are not that country's law
        groups.append([passage_dict(p) for p in result.passages if p.country == country][:PER_ASPECT])
    return unique_passages(groups)


def column(cells: list[dict], refs: set[str], not_specified: str) -> tuple[dict, int]:
    """aspect -> {text, citation}; and the number of cells rejected for a missing or unknown citation."""
    out, rejected = {}, 0
    for cell in cells:
        aspect = cell.get("aspect")
        if aspect not in prompts.ASPECTS or aspect in out:
            continue
        value, citation = str(cell.get("value", "")).strip(), cell.get("citation")
        if citation in refs and value:
            out[aspect] = {"text": value, "citation": citation}
        else:
            if value and value.rstrip(".").lower() != not_specified.rstrip(".").lower():
                rejected += 1          # a claim without a valid citation, "none" included
            out[aspect] = {"text": not_specified, "citation": None}
    for aspect in prompts.ASPECTS:
        out.setdefault(aspect, {"text": not_specified, "citation": None})
    return out, rejected


@traced("compare_countries")
async def compare_countries(state) -> dict:
    lang = state["language"]
    as_of = state["dates"][0]
    notes = list(state.get("notes", []))
    if len(state["dates"]) > 1:
        notes.append(f"A comparison is for one date: {as_of} was used.")
    kb = await asyncio.to_thread(retriever)
    not_specified = text(lang, "not_specified")
    cells = {aspect: {} for aspect in prompts.ASPECTS}
    citations = []
    for country in state["countries"]:
        passages = await country_passages(kb, country, date.fromisoformat(as_of))
        refs = list(dict.fromkeys(p["ref"] for p in passages))
        system = prompts.COMPARE_SYSTEM.format(country=prompts.COUNTRY_NAMES[country], as_of=as_of,
                                               language=prompts.LANGUAGE_NAMES[lang])
        result = await complete_json(system, prompts.compare_user(passages), prompts.compare_schema(refs),
                                     f"compare_{country.lower()}", max_tokens=1500)
        col, rejected = column(result.data.get("cells") or [], set(refs), not_specified)
        if rejected:
            notes.append(f"{prompts.COUNTRY_NAMES[country]}: {rejected} cell(s) without a valid citation were "
                         "replaced by 'not specified'.")
        for aspect, cell in col.items():
            cells[aspect][country] = cell
            if cell["citation"]:
                citations.append(cell["citation"])
    comparison = {"as_of": as_of, "countries": state["countries"],
                  "aspects": [{"id": key, "label": label} for key, (label, _) in prompts.ASPECTS.items()],
                  "cells": cells}
    total = len(prompts.ASPECTS) * len(state["countries"])
    cited = sum(1 for row in cells.values() for cell in row.values() if cell["citation"])
    names = ", ".join(prompts.COUNTRY_NAMES[c] for c in state["countries"])
    return reply(text(lang, "compare_summary", countries=names, date=as_of, cited=cited, total=total),
                 comparison=comparison, citations=list(dict.fromkeys(citations)), notes=notes)
