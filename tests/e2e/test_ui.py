"""Browser tests (Playwright) against the real app: Validate, Assistant and Compare tabs (scripted model)."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_validate_the_demo_sample(page, app_url):
    page.goto(f"{app_url}/#validate")
    page.select_option("#sample", "ks-demo-old-rate-no-ksk-total")
    expect(page.locator("#source")).to_contain_text("pre-approved")
    page.click("#validate")
    expect(page.locator("#verdict")).to_have_text("Not valid")
    expect(page.locator("#findings tbody tr td:first-child")).to_have_text(["KS-04", "KS-05"])
    expect(page.locator("#findings")).to_contain_text("on 2026-03-05 the rate is 10 %")
    expect(page.locator("#expected")).to_contain_text("matches the expected: KS-04, KS-05")


def test_sample_parameters_are_applied(page, app_url):
    page.goto(f"{app_url}/#validate")
    page.select_option("#sample", "vd-09-cleared-without-clearance-id")
    expect(page.locator("#stage")).to_have_value("cleared")
    page.click("#validate")
    expect(page.locator("#findings tbody tr td:first-child")).to_have_text(["VD-09"])
    page.select_option("#sample", "ks-b2b-valid")
    expect(page.locator("#stage")).to_have_value("pre_clearance")
    page.click("#validate")
    expect(page.locator("#verdict")).to_have_text("Valid")


def test_uploaded_invoice_text_is_shown_as_text_not_html(page, app_url):
    payload = '<img src=x onerror="window.__xss=1">'
    escaped = payload.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    xml = ('<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
           'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
           f'<cbc:ID>{escaped}</cbc:ID><cbc:IssueDate>{escaped}</cbc:IssueDate><cbc:Note>{escaped}</cbc:Note>'
           '</Invoice>')
    page.goto(f"{app_url}/#validate")
    page.set_input_files("#file", files=[{"name": "evil.xml", "mimeType": "application/xml",
                                          "buffer": xml.encode()}])
    expect(page.locator("#source")).to_contain_text("evil.xml")
    page.click("#validate")
    expect(page.locator("#findings")).to_contain_text(f"The issue date '{payload}'")
    page.click("text=Invoice XML")
    expect(page.locator("#xml")).to_contain_text("onerror")
    assert page.evaluate("window.__xss") is None
    assert page.locator("img").count() == 0


# --- Assistant and Compare (the model is the scripted fake) --------------------------------------------------------

def route(intent, countries=(), dates=()):
    return {"intent": intent, "countries": list(countries), "date_phrases": list(dates), "search_query": ""}


def test_assistant_answer_with_dates_and_a_source_chip(page, app_url, fake_lm):
    fake_lm.script("route", route("question", ["VD"], ["30 June 2026", "1 July 2026"]))
    answer_text = "On 30 June 2026: no [VD-AM-03 §2]. On 1 July 2026: yes [VD-AM-03 §2]."
    fake_lm.script("grounded_answer", {"in_documents": True, "answer": answer_text})
    page.goto(app_url)
    page.fill("#message", "Is a small Valdorian company obliged to use VCP on 30 June 2026? And on 1 July?")
    page.click("#send")
    answer = page.locator(".msg.assistant").last
    expect(answer).to_contain_text("On 1 July 2026: yes")
    expect(answer.get_by_test_id("dates")).to_have_text("as of 2026-06-30, 2026-07-01 (from the question)")
    expect(page.locator("#progress")).to_contain_text("answering")
    answer.locator(".chip", has_text="VD-AM-03 §2").click()
    expect(page.locator("#passage-ref")).to_have_text("VD-AM-03 §2")
    expect(page.locator("#passage-text")).to_contain_text("1 July 2026")


def test_model_text_is_shown_as_text_not_html(page, app_url, fake_lm):
    payload = '<img src=x onerror="window.__xss=1">'
    fake_lm.script("route", route("out_of_scope"))
    page.goto(app_url)
    page.fill("#message", payload)
    page.click("#send")
    expect(page.locator(".msg.user")).to_have_text(payload)
    expect(page.locator(".msg.assistant")).to_contain_text("outside what I can help with")
    assert page.evaluate("window.__xss") is None and page.locator("img").count() == 0


def test_validate_an_attached_sample_in_the_chat(page, app_url, fake_lm):
    fake_lm.script("route", route("validate", ["KS"]))
    fake_lm.script("explain_findings", lambda p: {"summary": "Fix the rate and add the KSK total.", "explanations": [
        {"rule_id": "KS-04", "explanation": "Old rate.", "likely_cause": "", "fix": "Use 10 %.",
         "citation": "KS-CL-01 §2"},
        {"rule_id": "KS-05", "explanation": "No KSK total.", "likely_cause": "", "fix": "Add it.",
         "citation": "none"}]})
    page.goto(app_url)
    page.select_option("#chat-sample", "ks-demo-old-rate-no-ksk-total")
    expect(page.locator("#attached")).to_contain_text("ks-demo-old-rate-no-ksk-total")
    page.fill("#message", "Please check this invoice")
    page.click("#send")
    answer = page.locator(".msg.assistant").last
    expect(answer.locator(".chat-findings tbody td.rule")).to_have_text(["KS-04", "KS-05"])
    expect(answer).to_contain_text("Fix the rate and add the KSK total.")
    expect(answer.get_by_test_id("dates")).to_contain_text("(invoice date)")


def test_compare_tab_renders_a_cited_table(page, app_url, fake_lm):
    def column(payload):
        refs = payload["response_format"]["json_schema"]["schema"]["properties"]["cells"]["items"]["properties"][
            "citation"]["enum"]
        return {"cells": [{"aspect": "model", "value": "Per the law.", "citation": refs[0]}]}

    fake_lm.script("route", route("compare", ["KS", "OL"], ["2026-05-15"]))
    fake_lm.script("compare_ks", column)
    fake_lm.script("compare_ol", column)
    page.goto(f"{app_url}/#compare")
    expect(page.locator("#compare-date")).to_have_value("2026-05-15")
    page.click("#compare")
    table = page.locator("#compare-table")
    expect(table.locator("thead th")).to_have_text(["As of 2026-05-15", "Kestria", "Orlavia"])
    expect(table.locator("tbody tr").first.locator(".chip")).to_have_count(2)
    expect(page.locator("#compare-summary")).to_contain_text("2 of 16 cells")
    assert "Compare Kestria and Orlavia on 2026-05-15" in fake_lm.calls("route")[0]["messages"][1]["content"]


def test_tabs_follow_the_address_hash(page, app_url):
    page.goto(app_url)
    expect(page.locator("#view-assistant")).to_be_visible()
    page.goto(f"{app_url}/#compare")          # same page, only the hash changes: no reload
    expect(page.locator("#view-compare")).to_be_visible()
    expect(page.locator("#view-assistant")).to_be_hidden()
    page.click("nav >> text=Validate")
    expect(page.locator("#view-validate")).to_be_visible()
    assert page.url.endswith("#validate")
