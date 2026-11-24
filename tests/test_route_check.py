"""The route check: when the calibrated one-letter route answer disagrees with the router or is not sure, the
assistant asks which intent is meant instead of guessing. Code rules and the Create-ticket button are not affected."""
import asyncio
import json
import math

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from test_requirements import nodes, run

from copilot import attachments, config, decisions
from copilot.decide import Action, Calibration, Decider
from copilot.decide.core import Decision
from copilot.graph.build import build_graph
from copilot.graph.run import stream_turn

CODES = {label: code for label, code in decisions.ROUTE.codes.items()}


def route_json(intent, countries=()):
    return {"intent": intent, "countries": list(countries), "date_phrases": [], "search_query": ""}


@pytest.fixture
def graph():
    return build_graph(InMemorySaver())


@pytest.fixture
def check(monkeypatch, tmp_path):
    """The route check on (T = 1 calibration); queue answers as {label: p} dicts or HTTP error codes."""
    monkeypatch.setattr(config, "DECISION_GATE", True)
    Calibration(decisions.ROUTE.id, config.LLM_MODEL, decisions.ROUTE.prompt_hash(), 1.0, 30, "2026-11-24", {}, {}
                ).save(tmp_path)
    answers, requests = [], []

    def handle(request):
        requests.append(json.loads(request.content))
        answer = answers.pop(0)
        if isinstance(answer, int):
            return httpx.Response(answer)
        top = [{"token": CODES[label], "logprob": math.log(p)} for label, p in answer.items()]
        return httpx.Response(200, json={"choices": [{"message": {"content": top[0]["token"]},
                                                       "logprobs": {"content": [{"top_logprobs": top}]}}]})
    monkeypatch.setattr(decisions, "decider", lambda: Decider(
        config.LLM_BASE_URL, config.LLM_MODEL, calibration_dir=tmp_path, transport=httpx.MockTransport(handle)))
    return answers, requests


def test_a_sure_agreeing_check_keeps_the_route(graph, fake_lm, check):
    answers, requests = check
    answers.append({"out_of_scope": 0.97, "question": 0.03})
    fake_lm.script("route", route_json("out_of_scope"))
    events = run(graph, "Tell me a joke")
    assert nodes(events) == ["route", "out_of_scope"]
    assert "Attachment: none" in requests[0]["messages"][1]["content"]


@pytest.mark.parametrize(("answer", "reason"), [({"question": 0.9, "out_of_scope": 0.1}, "route-disagrees"),
                                                ({"out_of_scope": 0.7, "question": 0.3}, "route-unsure")])
def test_a_disagreeing_or_unsure_check_asks_instead(graph, fake_lm, check, answer, reason):
    check[0].append(answer)
    fake_lm.script("route", route_json("out_of_scope"))
    events = run(graph, "Can you help me with something?")
    final = events[-1]
    assert nodes(events) == ["route", "clarify"] and final["intent"] == "clarify"
    assert final["answer"].startswith("Just to be sure: do you want me to help with something outside these "
                                      "documents, or answer a question about the rules?")
    assert reason in final["notes"][0]


def test_no_usable_answer_keeps_the_route(graph, fake_lm, check):
    check[0].append(503)
    fake_lm.script("route", route_json("out_of_scope"))
    assert nodes(run(graph, "Tell me a joke")) == ["route", "out_of_scope"]


def test_code_rules_are_not_second_guessed(graph, fake_lm, check):
    check[0].append({"question": 0.99, "validate": 0.01})
    fake_lm.script("route", route_json("question", ["OL"]))
    attachment_id = attachments.save((config.SAMPLES_DIR / "ol-b2b-valid.xml").read_bytes())

    async def collect():
        return [e async for e in stream_turn(graph, "rc", "Check this invoice", attachment_id)]
    events = asyncio.run(collect())     # the router said "question"; the code rule made it "validate"
    assert "validate_invoice" in nodes(events) and "clarify" not in nodes(events)


def test_bulgarian_clarifying_question(graph, fake_lm, check):
    check[0].append({"compare": 0.6, "question": 0.4})
    fake_lm.script("route", route_json("question"))
    events = run(graph, "Валдория и Кестрия?")
    assert events[-1]["answer"].startswith("За да съм сигурен: искате ли да отговоря на въпрос за правилата, или да "
                                           "сравня държавите?")


def test_route_check_unit():
    def d(probs, label, action):
        return Decision("einvoice.route", label, probs.get(label), None, probs, {}, action, "policy", 0, None)
    assert decisions.route_check("question", d({}, None, Action.CONFIRM)) is None
    assert decisions.route_check("question", d({"question": 0.9}, "question", Action.ACT)) is None
    assert decisions.route_check("question", d({"compare": 0.9}, "compare", Action.ACT)) == "route-disagrees"
    assert decisions.route_check("question", d({"question": 0.7}, "question", Action.CONFIRM)) == "route-unsure"
    context = decisions.route_context([{"role": "user", "content": "x" * 500}], True, False)
    assert context["history"] == "user: " + "x" * 300 and context["attachment"] == "an invoice is attached"
