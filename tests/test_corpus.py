"""The corpus stays consistent with itself, with the rules and with the key facts (ARCHITECTURE.md §6.3)."""
import re
from datetime import date, timedelta

import pytest

from copilot.corpus.loader import Document, load_corpus, load_facts, parse_document
from copilot.rules.definitions import load_rules

DOCS = {d.doc_id: d for d in load_corpus(include_test=True)}
PUBLIC_DOCS = {k: d for k, d in DOCS.items() if not d.test_only}
RULES = load_rules()


def spelled(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def test_the_e1_corpus_is_complete():
    assert set(DOCS) == {"COM-02", "COM-03", "VD-LAW-01", "VD-TS-01", "VD-TS-02", "VD-AM-03", "VD-FAQ-01",
                         "KS-LAW-01", "KS-TS-01", "KS-CL-00", "KS-CL-01", "OL-LAW-01", "OL-AM-12", "OL-TS-01",
                         "TEST-99"}
    assert "TEST-99" not in {d.doc_id for d in load_corpus()}  # only with include_test


@pytest.mark.parametrize("doc_id", sorted(DOCS))
def test_each_document_has_numbered_sections(doc_id):
    doc = DOCS[doc_id]
    numbers = [s.number for s in doc.sections]
    assert numbers == list(range(1, len(numbers) + 1)) and 2 <= len(numbers) <= 8
    assert all(s.text for s in doc.sections)
    assert doc.title in doc.body  # the H1 repeats the title


@pytest.mark.parametrize("doc_id", sorted(DOCS))
def test_announced_dates_appear_in_the_text(doc_id):
    doc = DOCS[doc_id]
    for day in doc.announces:
        assert spelled(day) in doc.body or day.isoformat() in doc.body, f"{doc_id}: {day} not in the text"


def test_superseded_versions_end_the_day_before_their_successor():
    for doc in DOCS.values():
        for old_id in doc.supersedes:
            old = DOCS[old_id]
            assert old.valid_to == doc.valid_from - timedelta(days=1), f"{old_id} -> {doc.doc_id}"
            assert old.country == doc.country and old.doc_type == doc.doc_type
    superseded = {old for d in DOCS.values() for old in d.supersedes}
    for doc in DOCS.values():
        assert (doc.valid_to is not None) == (doc.doc_id in superseded), doc.doc_id


def test_two_time_axes_an_amendment_is_valid_before_the_date_it_announces():
    # The demo question "obliged on 30 June 2026?" must find the amendment that moves the date to 1 July 2026.
    amendment = DOCS["VD-AM-03"]
    assert amendment.valid_on(date(2026, 6, 30)) and date(2026, 7, 1) in amendment.announces
    assert not DOCS["VD-TS-01"].valid_on(date(2026, 1, 1)) and DOCS["VD-TS-02"].valid_on(date(2026, 1, 1))
    assert DOCS["KS-CL-00"].valid_on(date(2026, 1, 14)) and not DOCS["KS-CL-00"].valid_on(date(2026, 1, 15))


def test_conflicting_sources_are_ranked_by_authority():
    # The outdated FAQ (authority 3) and the original Act (1) say 2027; the later amendment (1) says 1 July 2026.
    faq, act, amendment = DOCS["VD-FAQ-01"], DOCS["VD-LAW-01"], DOCS["VD-AM-03"]
    assert "1 January 2027" in faq.body and "1 January 2027" in act.body
    assert amendment.authority == act.authority < faq.authority and amendment.published > act.published


def test_the_unofficial_comparison_is_deliberately_incomplete():
    # COM-03 omits Orlavia's business-to-consumer scope; the agent must prefer the country documents.
    overview = DOCS["COM-03"]
    assert overview.authority == 3 and "consumer" not in overview.section(4).text
    assert "business-to-consumer" in DOCS["OL-LAW-01"].body


def test_every_rule_id_in_the_documents_exists_and_every_rule_is_described():
    rule_ids = {r.id for r in RULES.all}
    mentioned = set().union(*(d.rule_ids for d in PUBLIC_DOCS.values()))
    assert mentioned - rule_ids == set()
    assert {r.id for r in RULES.all if not r.internal} - mentioned == set()


@pytest.mark.parametrize("rule_id", sorted(r.id for r in load_rules().all))
def test_each_rule_reference_points_to_a_section_that_names_the_rule(rule_id):
    rule = RULES.get(rule_id)
    sections = []
    for ref in rule.doc_ref:
        doc_id, number = ref.split(" §")
        section = DOCS[doc_id].section(int(number))
        assert section is not None, ref
        sections.append(section.text)
    # A rule is named in at least one of the sections it cites (a code list section may cite it by meaning).
    assert any(rule_id in text for text in sections)


@pytest.mark.parametrize("name", sorted(load_facts()))
def test_key_facts_match_the_documents(name):
    fact = load_facts()[name]
    text = re.sub(r"\s+", " ", DOCS[fact["doc"]].body)  # line breaks in the Markdown are not breaks in the text
    assert re.search(fact["pattern"], text, re.I), f"{name} not found in {fact['doc']}"


def test_no_real_countries_or_institutions_are_named():
    text = " ".join(d.body for d in DOCS.values()).lower()
    for real in ("austria", "germany", "france", "italy", "spain", "poland", "hungary", "peppol", "en 16931"):
        assert real not in text


@pytest.mark.parametrize("broken, message", [
    ("no front matter", "no front matter"),
    ("---\ndoc_id: VD-XX-01\ntitle: t\ncountry: XX\n---\n", "country"),
    ("---\ndoc_id: VD-AM-09\ntitle: t\ncountry: VD\ndoc_type: law\nversion: 1\npublished: 2026-01-02\n"
     "valid_from: 2026-01-01\nauthority: 1\nlang: en\n---\n", "before the publication"),
])
def test_invalid_documents_are_rejected(broken, message):
    with pytest.raises(ValueError, match=message):
        parse_document(broken)


def test_folder_and_test_only_mismatches_are_rejected(tmp_path):
    good = (DOCS["VD-AM-03"].model_dump(exclude={"body", "sections"}))
    header = "---\n" + "\n".join(f"{k}: {v if not isinstance(v, list) else [str(x) for x in v]}"
                                 for k, v in good.items() if v is not None) + "\n---\n## 1. A\ntext\n"
    for folder in ("common", "valdoria", "kestria", "orlavia", "test-only"):
        (tmp_path / folder).mkdir()
    (tmp_path / "kestria" / "x.md").write_text(header, encoding="utf-8")
    with pytest.raises(ValueError, match="does not match the folder"):
        load_corpus(tmp_path)
    (tmp_path / "kestria" / "x.md").unlink()
    (tmp_path / "valdoria" / "a.md").write_text(header, encoding="utf-8")
    (tmp_path / "valdoria" / "b.md").write_text(header, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate doc_id"):
        load_corpus(tmp_path)


def test_document_model_validity_window():
    doc = Document(doc_id="KS-CL-09", title="t", country="KS", doc_type="code_list", version="1",
                   published=date(2026, 1, 1), valid_from=date(2026, 1, 1), valid_to=date(2026, 1, 31),
                   authority=2, lang="en")
    assert doc.valid_on(date(2026, 1, 31)) and not doc.valid_on(date(2026, 2, 1))
    with pytest.raises(ValueError, match="valid_to is before"):
        Document(**{**doc.model_dump(), "valid_to": date(2025, 12, 31)})
