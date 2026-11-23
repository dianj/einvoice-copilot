"""Browser tests (Playwright) for the Validate tab, against the real app."""
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def test_validate_the_demo_sample(page, app_url):
    page.goto(app_url)
    page.select_option("#sample", "ks-demo-old-rate-no-ksk-total")
    expect(page.locator("#source")).to_contain_text("pre-approved")
    page.click("#validate")
    expect(page.locator("#verdict")).to_have_text("Not valid")
    expect(page.locator("#findings tbody tr td:first-child")).to_have_text(["KS-04", "KS-05"])
    expect(page.locator("#findings")).to_contain_text("on 2026-03-05 the rate is 10 %")
    expect(page.locator("#expected")).to_contain_text("matches the expected: KS-04, KS-05")


def test_sample_parameters_are_applied(page, app_url):
    page.goto(app_url)
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
    page.goto(app_url)
    page.set_input_files("#file", files=[{"name": "evil.xml", "mimeType": "application/xml",
                                          "buffer": xml.encode()}])
    expect(page.locator("#source")).to_contain_text("evil.xml")
    page.click("#validate")
    expect(page.locator("#findings")).to_contain_text(f"The issue date '{payload}'")
    page.click("text=Invoice XML")
    expect(page.locator("#xml")).to_contain_text("onerror")
    assert page.evaluate("window.__xss") is None
    assert page.locator("img").count() == 0
