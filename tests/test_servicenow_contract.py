"""One contract for every ticket backend: the local fake, the REST adapter against a fake Table API, and (with
SN_LIVE_TESTS=1 and the SN_* settings) the REST adapter against a real ServiceNow instance."""
import asyncio
import os
import uuid
from datetime import date
from pathlib import Path

import pytest
from fake_servicenow import INSTANCE, PASSWORD, TABLE, USER, FakeServiceNowAPI

from copilot import config
from copilot.integrations.servicenow import FakeServiceNow, RestServiceNow, TicketSystemError, ticket_system
from copilot.integrations.servicenow.models import RequirementDraft, idempotency_key

LIVE = os.environ.get("SN_LIVE_TESTS") == "1"


def draft(**changes) -> RequirementDraft:
    values = {"title": "Orlavia: report B2B invoices to ORTS within 24 hours", "country": "OL",
              "effective_date": date(2026, 4, 1), "user_story": "As a localization analyst, I want ...",
              "acceptance_criteria": ["An invoice is reported within 24 hours of IssueTime.", "The QR code is set."],
              "rule_ids": ["OL-05"], "doc_refs": ["OL-AM-12 §2", "OL-TS-01 §4"], "priority": "high",
              "as_of": date(2026, 5, 15)}
    return RequirementDraft(**{**values, **changes})


def key() -> str:
    return idempotency_key(uuid.uuid4().hex, {"n": uuid.uuid4().hex})


@pytest.fixture(params=["fake", "rest", pytest.param("rest-live", marks=pytest.mark.skipif(
    not LIVE, reason="set SN_LIVE_TESTS=1 and the SN_* settings to test a real instance"))])
def backend(request, tmp_path):
    if request.param == "fake":
        return FakeServiceNow(tmp_path / "app.sqlite")
    if request.param == "rest":
        return RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=FakeServiceNowAPI().transport,
                              retry_delay=0)
    return RestServiceNow()


def test_create_then_read_back(backend):
    async def scenario():
        ref = await backend.create_requirement(draft(), key(), "thread-1")
        detail = await backend.get_ticket(ref.number)
        recent = await backend.list_recent(5)
        return ref, detail, recent
    ref, detail, recent = asyncio.run(scenario())
    assert ref.created and ref.number.startswith("LOCREQ")
    assert detail.title == draft().title and detail.country == "OL" and detail.effective_date == "2026-04-01"
    assert detail.acceptance_criteria == draft().acceptance_criteria
    assert detail.rule_ids == ["OL-05"] and detail.doc_refs == ["OL-AM-12 §2", "OL-TS-01 §4"]
    assert detail.source_thread == "thread-1" and detail.priority == "high"
    assert recent[0].number == ref.number


def test_the_same_key_returns_the_existing_ticket(backend):
    k = key()

    async def scenario():
        first = await backend.create_requirement(draft(), k, "t")
        second = await backend.create_requirement(draft(title="Changed later"), k, "t")
        other = await backend.create_requirement(draft(), key(), "t")
        return first, second, other
    first, second, other = asyncio.run(scenario())
    assert (first.created, second.created, other.created) == (True, False, True)
    assert second.number == first.number and other.number != first.number


def test_numbers_are_consecutive(backend):
    async def scenario():
        return [await backend.create_requirement(draft(), key(), "t") for _ in range(3)]
    numbers = [int(ref.number.removeprefix("LOCREQ")) for ref in asyncio.run(scenario())]
    assert numbers[1] == numbers[0] + 1 and numbers[2] == numbers[0] + 2


def test_unknown_ticket_and_a_draft_without_date_or_rules(backend):
    async def scenario():
        ref = await backend.create_requirement(draft(effective_date=None, rule_ids=[]), key(), "t")
        return await backend.get_ticket(ref.number), await backend.get_ticket("LOCREQ9999999")
    detail, missing = asyncio.run(scenario())
    assert detail.effective_date is None and detail.rule_ids == []
    assert missing is None


# --- the REST adapter's own behaviour -----------------------------------------------------------------------------

def rest(api: FakeServiceNowAPI, **kwargs) -> RestServiceNow:
    return RestServiceNow(INSTANCE, kwargs.pop("user", USER), kwargs.pop("password", PASSWORD), TABLE,
                          transport=api.transport, retry_delay=0)


def test_rest_retries_once_on_503_and_429():
    api = FakeServiceNowAPI()
    api.fail_next = 1
    ref = asyncio.run(rest(api).create_requirement(draft(), key(), "t"))
    assert ref.created
    api.rate_limited_next = 1
    assert len(asyncio.run(rest(api).list_recent())) == 1


def test_rest_failures_become_safe_errors():
    api = FakeServiceNowAPI()
    api.down = True
    with pytest.raises(TicketSystemError, match="503"):
        asyncio.run(rest(api).list_recent())
    with pytest.raises(TicketSystemError, match="refused the integration user"):
        asyncio.run(rest(FakeServiceNowAPI(), password="wrong").list_recent())
    with pytest.raises(TicketSystemError, match="https"):
        RestServiceNow("http://dev1.service-now.com", USER, PASSWORD, TABLE)


def test_rest_connection_errors_are_retried_then_reported():
    import httpx

    attempts = []

    def refuse(request):
        attempts.append(request)
        raise httpx.ConnectError("refused")
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(refuse), retry_delay=0)
    with pytest.raises(TicketSystemError, match="not reachable"):
        asyncio.run(adapter.list_recent())
    assert len(attempts) == 2


def test_rest_keeps_callers_text_out_of_the_query():
    api = FakeServiceNowAPI()
    assert asyncio.run(rest(api).get_ticket("LOCREQ0001001^ORnumberISNOTEMPTY")) is None
    assert api.calls == []
    with pytest.raises(ValueError):
        asyncio.run(rest(api).create_requirement(draft(), "x^ORu_idempotency_keyISNOTEMPTY", "t"))


def test_rest_links_to_the_record():
    ref = asyncio.run(rest(FakeServiceNowAPI()).create_requirement(draft(), key(), "t"))
    assert ref.url == f"{INSTANCE}/{TABLE}.do?sys_id={ref.sys_id}"


def test_backend_from_settings(monkeypatch):
    monkeypatch.setattr(config, "SN_BACKEND", "fake")
    assert isinstance(ticket_system(), FakeServiceNow)
    monkeypatch.setattr(config, "SN_BACKEND", "rest")
    monkeypatch.setattr(config, "SN_INSTANCE_URL", INSTANCE)
    assert isinstance(ticket_system(), RestServiceNow)


def test_fake_backend_defaults_to_the_app_database():
    assert FakeServiceNow().path == Path(config.APP_DB)


# --- answers that are not the API, and a POST that may have been sent (review T17.A2, A3) ---------------------------

def test_rest_an_html_page_is_a_safe_error():
    """A sleeping developer instance or a proxy answers 200 with an HTML page, not JSON."""
    import httpx

    def asleep(request):
        return httpx.Response(200, html="<html><body>Your instance is hibernating</body></html>")
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(asleep), retry_delay=0)
    with pytest.raises(TicketSystemError, match="did not answer with its API"):
        asyncio.run(adapter.list_recent())

    def broken_json(request):
        return httpx.Response(200, content=b"{not json", headers={"content-type": "application/json"})
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(broken_json),
                             retry_delay=0)
    with pytest.raises(TicketSystemError, match="did not answer with its API"):
        asyncio.run(adapter.create_requirement(draft(), key(), "t"))


def test_rest_a_post_that_timed_out_is_looked_up_not_sent_again():
    """The instance stored the record but the answer never arrived (ReadTimeout). Sending the POST again would make a
    second ticket; the adapter looks the idempotency key up again instead."""
    import httpx

    api = FakeServiceNowAPI()

    def slow_answer(request):
        response = api.handle(request)
        if request.method == "POST":
            raise httpx.ReadTimeout("the answer did not arrive", request=request)
        return response
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(slow_answer),
                             retry_delay=0)
    k = key()
    ref = asyncio.run(adapter.create_requirement(draft(), k, "t"))
    assert [m for m, _ in api.calls] == ["GET", "POST", "GET"]
    assert len(api.records) == 1 and ref.number == api.records[0]["number"] and ref.created


def test_rest_a_post_that_timed_out_before_storing_is_reported():
    import httpx

    api = FakeServiceNowAPI()

    def lost(request):
        if request.method == "POST":
            api.calls.append(("POST", request.url.path))
            raise httpx.ReadTimeout("no answer", request=request)
        return api.handle(request)
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(lost), retry_delay=0)
    with pytest.raises(TicketSystemError, match="not reachable"):
        asyncio.run(adapter.create_requirement(draft(), key(), "t"))
    assert [m for m, _ in api.calls] == ["GET", "POST", "GET"] and api.records == []


def test_rest_a_post_is_retried_when_it_never_left():
    """A refused connection means nothing was sent: one retry is safe."""
    import httpx

    api, refused = FakeServiceNowAPI(), []

    def refuse_first_post(request):
        if request.method == "POST" and not refused:
            refused.append(request)
            raise httpx.ConnectError("refused", request=request)
        return api.handle(request)
    adapter = RestServiceNow(INSTANCE, USER, PASSWORD, TABLE, transport=httpx.MockTransport(refuse_first_post),
                             retry_delay=0)
    assert asyncio.run(adapter.create_requirement(draft(), key(), "t")).created and len(api.records) == 1
