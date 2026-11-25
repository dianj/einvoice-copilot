"""Conflicts between documents are decided in code (review T17.C3): when the answer rests on a passage that states
one member of a fact family (corpus/facts.yaml: `VD.b2b_all_from`, `..._original`, `..._outdated_faq`) and another
retrieved passage states a different value of the same family, code adds the sentence that names the conflict, with
both citations and the rule that decides it (authority first, then the later publication)."""
from datetime import date

from test_graph import final, graph, route_answer, run  # noqa: F401  (graph is a fixture)

from copilot.corpus.loader import load_facts
from copilot.graph.nodes.conflicts import conflict_sentences, find_conflicts


def passage(doc_id, section, text, authority, published, doc_type, title=None):
    return {"doc_id": doc_id, "section": section, "ref": f"{doc_id} §{section}", "text": text,
            "authority": authority, "published": published, "doc_type": doc_type, "title": title or doc_id}


AMENDMENT = passage("VD-AM-03", 2, "Business-to-business invoices issued by all VAT-registered taxpayers must be "
                    "cleared through VCP from\n1 July 2026.", 1, "2026-03-10", "amendment",
                    "Amendment A-2026/03 to the Valdoria e-Invoicing Act")
FAQ = passage("VD-FAQ-01", 1, "All other VAT-registered companies must\nclear their business-to-business invoices "
              "from 1 January 2027.", 3, "2025-06-20", "faq", "VCP frequently asked questions")
LAW = passage("VD-LAW-01", 2, "(3) Invoices for business-to-business supplies issued by all other VAT-registered "
              "taxpayers shall be cleared through\nVCP from 1 January 2027.", 1, "2024-11-01", "law")
OTHER = passage("KS-LAW-01", 4, "Invoices are archived for ten years.", 1, "2024-01-01", "law")


def test_the_amendment_wins_and_both_losers_are_named():
    [conflict] = find_conflicts(["VD-AM-03 §2"], [AMENDMENT, FAQ, LAW, OTHER], load_facts())
    assert conflict.winner["ref"] == "VD-AM-03 §2" and conflict.winner_value == date(2026, 7, 1)
    assert [(p["ref"], v) for p, v in conflict.losers] == [("VD-FAQ-01 §1", date(2027, 1, 1)),
                                                          ("VD-LAW-01 §2", date(2027, 1, 1))]
    [sentence] = conflict_sentences([conflict], "en")
    assert "[VD-FAQ-01 §1]" in sentence and "[VD-AM-03 §2]" in sentence and "[VD-LAW-01 §2]" in sentence
    assert "1 January 2027" in sentence and "1 July 2026" in sentence
    [bg] = conflict_sentences([conflict], "bg")
    assert "1 юли 2026 г." in bg and "1 януари 2027 г." in bg and "[VD-FAQ-01 §1]" in bg


def test_the_winner_is_decided_by_code_even_when_the_answer_cites_the_loser():
    """The answer rests on the FAQ: code still names the amendment as the one that applies."""
    [conflict] = find_conflicts(["VD-FAQ-01 §1"], [FAQ, AMENDMENT], load_facts())
    assert conflict.winner["ref"] == "VD-AM-03 §2" and [p["ref"] for p, _ in conflict.losers] == ["VD-FAQ-01 §1"]


def test_no_conflict_without_a_cited_family_member_or_a_second_value():
    facts = load_facts()
    assert find_conflicts(["KS-LAW-01 §4"], [OTHER, AMENDMENT, FAQ], facts) == []   # the answer is about something else
    assert find_conflicts(["VD-AM-03 §2"], [AMENDMENT, OTHER], facts) == []          # the FAQ was not retrieved


# Close to the words of VD-AM-03 §2 and VD-FAQ-01 §1, so the test embedder and BM25 find both.
QUERY = ("business-to-business invoices all VAT-registered taxpayers companies must be cleared through VCP from "
         "1 July 2026 or 1 January 2027")


def test_the_answer_gets_the_conflict_sentence_and_both_citations(graph, fake_lm):  # noqa: F811
    """End to end: the model cites only the amendment and does not mention the FAQ (Gemma's 2 misses in 15)."""
    fake_lm.script("route", route_answer("question", ["VD"], [], QUERY))

    def amendment_only(payload):
        return {"in_documents": True, "answer": "All businesses must clear B2B invoices from 1 July 2026 "
                                                "[VD-AM-03 §2]."}
    fake_lm.script("grounded_answer", amendment_only)
    events = run(graph, "From when must all Valdorian businesses use B2B e-invoicing?")
    retrieved = {p["ref"] for e in events if e["event"] == "sources" for r in e["retrievals"] for p in r["passages"]}
    assert {"VD-AM-03 §2", "VD-FAQ-01 §1"} <= retrieved
    result = final(events)
    assert "[VD-FAQ-01 §1]" in result["answer"] and "1 January 2027" in result["answer"]
    assert result["citations"][0] == "VD-AM-03 §2" and "VD-FAQ-01 §1" in result["citations"]
    assert any("conflict" in n.lower() for n in result["notes"])


def test_an_answer_that_already_names_the_conflict_is_left_alone(graph, fake_lm):  # noqa: F811
    fake_lm.script("route", route_answer("question", ["VD"], [], QUERY))

    def names_it(payload):
        return {"in_documents": True, "answer": "From 1 July 2026 [VD-AM-03 §2]. The FAQ [VD-FAQ-01 §1] still says "
                                                "1 January 2027, but the later amendment [VD-AM-03 §2] applies."}
    fake_lm.script("grounded_answer", names_it)
    result = final(run(graph, "From when must all Valdorian businesses use B2B e-invoicing?"))
    assert result["answer"].count("VD-FAQ-01 §1") == 1


def test_citing_both_documents_is_not_naming_the_conflict(graph, fake_lm):  # noqa: F811
    """Gemma in the T17 dev run (2 of 2): it cited the original law and the amendment, but said nothing about the old
    date. Citing two documents is not naming their conflict: the sentence is added."""
    fake_lm.script("route", route_answer("question", ["VD"], [], QUERY + " Article 4 large taxpayers"))

    def both_cited_conflict_unsaid(payload):
        return {"in_documents": True,
                "answer": "Large taxpayers clear B2B invoices from 1 January 2026 [VD-LAW-01 §2]. For all other "
                          "taxpayers, invoices up to 30 June 2026 need no clearance [VD-AM-03 §2]."}
    fake_lm.script("grounded_answer", both_cited_conflict_unsaid)
    events = run(graph, "From when must all Valdorian businesses use B2B e-invoicing?")
    retrieved = {p["ref"] for e in events if e["event"] == "sources" for r in e["retrievals"] for p in r["passages"]}
    assert {"VD-AM-03 §2", "VD-LAW-01 §2"} <= retrieved
    result = final(events)
    assert "1 January 2027" in result["answer"] and "1 July 2026" in result["answer"]


def test_conflict_named_needs_every_value_in_the_text():
    from copilot.graph.nodes.conflicts import conflict_named

    [conflict] = find_conflicts(["VD-AM-03 §2"], [AMENDMENT, FAQ], load_facts())
    assert conflict_named(conflict, "From 1 July 2026; the FAQ still says 1 January 2027.", "en")
    assert not conflict_named(conflict, "From 1 July 2026 [VD-AM-03 §2] [VD-FAQ-01 §1].", "en")
    assert conflict_named(conflict, "От 1 юли 2026; FAQ все още посочва 1 януари 2027 г.", "bg")
