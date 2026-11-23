"""extract_date: the model only copied the date phrases; code turns them into dates.

`dateparser` reads English and Bulgarian phrases relative to "today" (`FROZEN_TODAY` in tests, evals and demos).
ISO and dd.mm.yyyy dates in the message are also picked up directly, in case the model missed one. A question
without a date is about today, and the answer says so.
"""
import asyncio
import re
from datetime import date, datetime

import dateparser

from copilot import config
from copilot.graph.nodes.common import traced

MAX_DATES = 3
ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b")


def parse_phrase(phrase: str, today: date) -> date | None:
    parsed = dateparser.parse(phrase, languages=["en", "bg"],
                              settings={"RELATIVE_BASE": datetime(today.year, today.month, today.day),
                                        "PREFER_DAY_OF_MONTH": "first", "DATE_ORDER": "DMY"})
    if parsed is None or not 2000 <= parsed.year <= 2100:
        return None
    return parsed.date()


def literal_dates(message: str) -> list[date]:
    found = []
    for y, m, d in ISO.findall(message):
        found.append((int(y), int(m), int(d)))
    for d, m, y in DMY.findall(message):
        found.append((int(y), int(m), int(d)))
    out = []
    for y, m, d in found:
        try:
            out.append(date(y, m, d))
        except ValueError:
            continue
    return out


def resolve_dates(phrases: list[str], message: str, today: date) -> tuple[list[date], list[str]]:
    """(dates, notes): up to three distinct dates in order, and a note for every phrase that could not be read."""
    dates, notes = [], []
    for phrase in phrases:
        day = parse_phrase(phrase, today)
        if day is None:
            notes.append(f"Could not read the date '{phrase[:60]}'.")
        else:
            dates.append(day)
    dates += literal_dates(message)
    distinct = sorted(set(dates))
    if len(distinct) > MAX_DATES:
        notes.append(f"Only the first {MAX_DATES} dates were used.")
    return distinct[:MAX_DATES], notes


@traced("extract_date")
async def extract_date(state) -> dict:
    today = config.today()
    # dateparser loads its language data on first use: keep that off the event loop
    dates, notes = await asyncio.to_thread(resolve_dates, state.get("date_phrases", []), state["user_input"],
                                           today)
    if not dates:
        return {"dates": [today.isoformat()], "date_source": "today",
                "notes": notes + [f"No date in the question: answered for today, {today.isoformat()}."]}
    return {"dates": [d.isoformat() for d in dates], "date_source": "question", "notes": notes}
