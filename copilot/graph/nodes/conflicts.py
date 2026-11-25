"""Conflicts between documents, decided in code.

`corpus/facts.yaml` groups facts into families by name: `VD.b2b_all_from` (what applies) and `VD.b2b_all_from_original`
/ `VD.b2b_all_from_outdated_faq` (what older or weaker documents still say). When the answer cites a passage that
states one member of a family, and another retrieved passage states a member with a different value, the conflict is
real and relevant. Code picks the passage that applies by the same rule the prompt gives the model (lower authority
number first: 1 = law or amendment, 2 = technical specification, 3 = FAQ or guide; then the later publication) and
writes the sentence that names the conflict with both citations. The model is asked to do this too; when it forgets
(Gemma, 2 runs in 15), the sentence is still there.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from copilot.graph.texts import text

MEMBER = re.compile(r"^(?P<family>.+?)_(?:original|outdated_[a-z]+)$")
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"],
          "bg": ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
                 "ноември", "декември"]}


@dataclass
class Conflict:
    family: str
    winner: dict                              # the passage that applies
    winner_value: object
    losers: list[tuple[dict, object]] = field(default_factory=list)   # (passage, the value it still gives)


def families(facts: dict) -> dict[str, list[tuple[str, dict]]]:
    """Fact name families with more than one member: {"VD.b2b_all_from": [(name, fact), ...]}."""
    groups: dict[str, list[tuple[str, dict]]] = {}
    for name, fact in facts.items():
        match = MEMBER.match(name)
        groups.setdefault(match.group("family") if match else name, []).append((name, fact))
    return {family: members for family, members in groups.items() if len(members) > 1}


def _states(passage: dict, fact: dict) -> bool:
    """The passage is from the fact's document and states it (the fact's own pattern, across line breaks)."""
    return passage.get("doc_id") == fact["doc"] and re.search(fact["pattern"], passage.get("text", ""), re.I | re.S)


def _applies_first(passage: dict) -> tuple:
    return int(passage.get("authority") or 9), _negated(str(passage.get("published") or ""))


def _negated(iso: str) -> tuple:
    return tuple(-int(part) for part in iso.split("-") if part.isdigit())   # later publication sorts first


def find_conflicts(cited: list[str], passages: list[dict], facts: dict) -> list[Conflict]:
    """Conflicts among the retrieved passages that touch what the answer cites."""
    cited_refs = set(cited)
    out = []
    for family, members in families(facts).items():
        stating = []                          # (passage, value), one per document, in retrieval order
        for p in passages:
            for _, fact in members:
                if _states(p, fact) and all(p["doc_id"] != q["doc_id"] for q, _ in stating):
                    stating.append((p, fact["value"]))
        if len({str(v) for _, v in stating}) < 2 or not cited_refs & {p["ref"] for p, _ in stating}:
            continue
        winner, value = min(stating, key=lambda pv: _applies_first(pv[0]))
        out.append(Conflict(family, winner, value, [(p, v) for p, v in stating if str(v) != str(value)]))
    return out


def say(value, lang: str) -> str:
    if isinstance(value, date):
        return (f"{value.day} {MONTHS['bg'][value.month - 1]} {value.year} г." if lang == "bg"
                else f"{value.day} {MONTHS['en'][value.month - 1]} {value.year}")
    return str(value)


def conflict_named(conflict: Conflict, answer: str, lang: str) -> bool:
    """The answer already states the value that applies and every value that is out of date ("1 July 2026" and
    "1 January 2027"; in Bulgarian without the trailing "г.")."""
    lower = answer.lower()
    values = [conflict.winner_value, *(v for _, v in conflict.losers)]
    return all(say(v, lang).removesuffix(" г.").lower() in lower for v in values)


def conflict_sentences(conflicts: list[Conflict], lang: str) -> list[str]:
    sentences = []
    for c in conflicts:
        older = "; ".join(text(lang, "conflict_loser", title=p.get("title") or p["doc_id"], ref=p["ref"],
                               value=say(v, lang)) for p, v in c.losers)
        sentences.append(text(lang, "conflict", older=older, title=c.winner.get("title") or c.winner["doc_id"],
                              ref=c.winner["ref"], value=say(c.winner_value, lang)))
    return sentences
