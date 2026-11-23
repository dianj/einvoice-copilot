"""The Python checks one by one, at their edges: check digits, tolerances, rate change dates, the QR hash."""
import copy
import hashlib
from decimal import Decimal

import pytest
from lxml import etree

from copilot.rules import checks
from copilot.rules.checks import Context, Invoice
from copilot.rules.parsing import NS
from samples.generator import Line, Party, Templates, build, edit


@pytest.fixture
def t():
    return Templates(seed=1)


def inv(spec_or_root) -> Invoice:
    root = spec_or_root if isinstance(spec_or_root, etree._Element) else build(spec_or_root)
    return Invoice(etree.ElementTree(root))


def set_text(root, path, value):
    root.xpath(path, namespaces=NS)[0].text = value
    return root


CTX = Context(country="KS", transaction_type="B2B", code_lists={"invoice_type": ["380", "381"], "currency": ["EUR"]})


# --- Valdorian tax ID (VD-TS-02 §4) -----------------------------------------------------------------------------

@pytest.mark.parametrize("tax_id, valid", [
    ("VD123456789", True),        # the example in the specification
    ("VD123456780", False),       # wrong check digit
    ("VD100000010", True),        # weighted sum 11, remainder 0: "11" gives the check digit 0
    ("VD100000011", False),
    ("VD100000070", False),       # remainder 1: "10" means no valid ID exists for these eight digits
    ("VD100000071", False),
    ("VD12345678", False),        # eight digits
    ("vd123456789", False),
    ("KS123456789", False),
    ("", False),
])
def test_valdorian_tax_id_check_digit(tax_id, valid):
    assert checks.vd_tax_id_valid(tax_id) is valid


@pytest.mark.parametrize("number, ok", [("INV-2026-000123", True), ("AB-2026-000001", True),
                                        ("ABCDE-2026-000001", False), ("inv-2026-000123", False),
                                        ("INV-2026-00123", False), ("INV-2025-000123", False)])
def test_valdorian_number_format_and_year(t, number, ok):
    assert (checks.vd_invoice_number_format(inv(edit(t.valdoria("2026-08-10"), number=number)), CTX) == []) is ok


def test_valdorian_clearance_id_format(t):
    spec = t.valdoria()
    assert checks.vd_clearance_id(inv(edit(spec, clearance_id="VCP-2026-00412345")), CTX) == []
    assert checks.vd_clearance_id(inv(edit(spec, clearance_id="VCP-2026-0041234")), CTX)[0].value == "VCP-2026-0041234"
    assert checks.vd_clearance_id(inv(spec), CTX)[0].value == ""


def test_valdorian_scope_check_needs_a_known_taxpayer_size(t):
    invoice = inv(t.valdoria())
    for size, failures in (("large", 0), ("other", 0), ("unknown", 1)):
        assert len(checks.vd_b2b_scope_known(invoice, Context("VD", "B2B", taxpayer_size=size))) == failures


# --- CORE arithmetic (COM-02 §5) --------------------------------------------------------------------------------

def test_line_net_tolerance_is_one_cent(t):
    root = build(t.kestria())
    net = Decimal(root.xpath("/*/cac:InvoiceLine[1]/cbc:LineExtensionAmount", namespaces=NS)[0].text)
    path = "/*/cac:InvoiceLine[1]/cbc:LineExtensionAmount"
    assert checks.line_net_amounts(inv(set_text(copy.deepcopy(root), path, f"{net + Decimal('0.01'):.2f}")), CTX) == []
    failures = checks.line_net_amounts(inv(set_text(copy.deepcopy(root), path, f"{net + Decimal('0.02'):.2f}")), CTX)
    assert failures == [("1", "/*/cac:InvoiceLine[1]/cbc:LineExtensionAmount")]


def test_line_net_uses_the_price_base_quantity(t):
    root = build(edit(t.kestria(), lines=[Line("Flour", Decimal(250), Decimal("12.00"), "AA", Decimal(10))]))
    assert checks.line_net_amounts(inv(root), CTX) == []
    price = root.xpath("/*/cac:InvoiceLine[1]/cac:Price", namespaces=NS)[0]
    etree.SubElement(price, f"{{{NS['cbc']}}}BaseQuantity").text = "100"      # the price is per 100 units
    assert len(checks.line_net_amounts(inv(root), CTX)) == 1
    set_text(root, "/*/cac:InvoiceLine[1]/cbc:LineExtensionAmount", "30.00")  # 250 x 12.00 / 100
    assert checks.line_net_amounts(inv(root), CTX) == []


def test_missing_or_non_numeric_amounts_are_findings_not_crashes(t):
    root = build(t.kestria())
    set_text(root, "/*/cac:InvoiceLine[2]/cbc:InvoicedQuantity", "two")
    set_text(root, "/*/cac:LegalMonetaryTotal/cbc:PayableAmount", "NaN")
    invoice = inv(root)
    assert [f.value for f in checks.line_net_amounts(invoice, CTX)] == ["2"]
    assert checks.payable_amount(invoice, CTX)[0].value == "missing"


def test_vat_breakdown_reports_the_subtotal_and_the_total(t):
    root = build(t.orlavia())
    set_text(root, "/*/cac:TaxTotal/cac:TaxSubtotal[1]/cbc:TaxAmount", "1.00")
    messages = [f.value for f in checks.vat_breakdown(inv(root), CTX)]
    assert len(messages) == 2 and "but the invoice states 1.00" in messages[0]
    assert "is not the sum of the subtotals" in messages[1]


def test_vat_breakdown_without_any_vat_total(t):
    root = build(t.orlavia())
    for node in root.xpath("/*/cac:TaxTotal", namespaces=NS):
        root.remove(node)
    assert checks.vat_breakdown(inv(root), CTX)[0].value == "there is no VAT total"


def test_vat_subtotal_without_a_rate(t):
    root = build(t.orlavia())
    percent = root.xpath("/*/cac:TaxTotal/cac:TaxSubtotal[1]/cac:TaxCategory/cbc:Percent", namespaces=NS)[0]
    percent.getparent().remove(percent)
    assert "lacks a taxable amount, tax amount or rate" in checks.vat_breakdown(inv(root), CTX)[0].value


def test_code_lists_come_from_the_context(t):
    invoice = inv(edit(t.orlavia(), type_code="389"))
    assert checks.type_code_in_list(invoice, CTX)[0].value == "389"
    with_extension = Context("OL", "B2B", code_lists={"invoice_type": ["380", "381", "389"]})
    assert checks.type_code_in_list(invoice, with_extension) == []


# --- Kestrian VAT rates (KS-CL-01) ------------------------------------------------------------------------------

@pytest.mark.parametrize("day, rate", [("2026-02-28", 12), ("2026-03-01", 10), ("2025-06-01", 12)])
def test_reduced_rate_changes_on_1_march_2026(day, rate):
    from datetime import date
    assert checks.ks_vat_rate("AA", date.fromisoformat(day)) == rate
    assert checks.ks_vat_rate("S", date.fromisoformat(day)) == 25
    assert checks.ks_vat_rate("Z", date.fromisoformat(day)) is None


def test_tax_point_date_wins_over_the_issue_date(t):
    spec = edit(t.kestria("2026-02-27"), issue_date="2026-03-02")      # 12 % rate, issued after the change
    assert len(checks.ks_vat_rates(inv(spec), CTX)) == 1
    assert checks.ks_vat_rates(inv(edit(spec, tax_point_date="2026-02-27")), CTX) == []


def test_bad_tax_point_date_and_unknown_category(t):
    spec = t.kestria()
    assert "not a date" in checks.ks_vat_rates(inv(edit(spec, tax_point_date="27/02/2026")), CTX)[0].value
    assert checks.ks_vat_rates(inv(edit(spec, issue_date="bad")), CTX) == []          # left to CORE-02
    odd = edit(spec, lines=[Line("Gift card", Decimal(1), Decimal("20.00"), "O", Decimal(0))])
    assert "not in the Kestrian VAT code list" in checks.ks_vat_rates(inv(odd), CTX)[0].value


def test_kestrian_tax_id_format(t):
    assert checks.ks_seller_tax_id(inv(t.kestria()), CTX) == []
    spec = edit(t.kestria(), seller=Party("Lunden Bakehouse AB", "KS123456789", endpoint="x"))
    assert checks.ks_seller_tax_id(inv(spec), CTX)[0].value == "KS123456789"


# --- Orlavian QR payload (OL-TS-01 §4) --------------------------------------------------------------------------

def test_qr_hash_matches_the_specification_by_hand():
    fields = ["OL1234567890", "OR/2026/1", "2026-05-04", "10:15:00", "118.00", "EUR"]
    by_hand = hashlib.sha256(b"OL1234567890|OR/2026/1|2026-05-04|10:15:00|118.00|EUR").hexdigest()[:16]
    assert checks.ol_qr_digest(fields) == by_hand == "88e777bffbc4246b"
    assert checks.ol_qr_payload(fields) == f"ORTS1|{'|'.join(fields)}|88e777bffbc4246b"


QR = "/*/cac:AdditionalDocumentReference/cbc:ID[@schemeID = 'ORTS-QR']"


def test_qr_payload_checks(t):
    root = build(t.orlavia())
    assert checks.ol_qr_hash(inv(root), CTX) == []
    payload = root.xpath(QR, namespaces=NS)[0].text
    parts = payload.split("|")

    wrong_number = copy.deepcopy(root)
    set_text(wrong_number, "/*/cbc:ID", "OR/2026/0001")
    assert checks.ol_qr_hash(inv(wrong_number), CTX)[0].value == "invoice number in the payload differ from the invoice"

    wrong_hash = set_text(copy.deepcopy(root), QR, "|".join(parts[:7] + ["0" * 16]))
    assert checks.ol_qr_hash(inv(wrong_hash), CTX)[0].value == "the hash is not the SHA-256 of the payload fields"

    short = set_text(copy.deepcopy(root), QR, "ORTS1|" + parts[1])
    assert "8 fields" in checks.ol_qr_hash(inv(short), CTX)[0].value

    assert checks.ol_qr_hash(inv(edit(t.orlavia(), qr=False)), CTX) == []    # OL-02 reports a missing payload


def test_orlavian_tax_id_format(t):
    assert checks.ol_seller_tax_id(inv(t.orlavia()), CTX) == []
    assert checks.ol_seller_tax_id(inv(edit(t.orlavia(), seller=Party("P", "OL123"))), CTX)[0].value == "OL123"


def test_every_python_check_in_the_yaml_exists():
    from copilot.rules.definitions import rules
    named = {r.check_body for r in rules().all if r.check_type == "python"}
    assert named == set(checks.CHECKS)
