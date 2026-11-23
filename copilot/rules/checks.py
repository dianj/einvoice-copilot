"""The `python:<name>` checks of the rule YAML files: pure functions of the invoice and the validation context.

Each check returns a list of failures; an empty list means the rule passed. A failure carries the value that fills
`{value}` in the rule's message and, when the problem is in one repeated element (a line, a VAT subtotal), a more
precise location. Checks never raise on missing or malformed data: they report it, or leave it to the rule that owns
it (for example, CORE-02 reports a bad issue date, so the date-dependent checks skip it).
"""
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import NamedTuple

from lxml import etree

from copilot.rules.parsing import NS

TOLERANCE = Decimal("0.01")
CENT = Decimal("0.01")
SELLER_TAX_ID = "/*/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
BUYER_TAX_ID = "/*/cac:AccountingCustomerParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"


class Failure(NamedTuple):
    value: str
    location: str | None = None


@dataclass
class Context:
    country: str | None
    transaction_type: str
    stage: str = "pre_clearance"
    taxpayer_size: str = "unknown"
    code_lists: dict[str, list[str]] = field(default_factory=dict)


class Invoice:
    """Small XPath helpers over a parsed UBL invoice."""

    def __init__(self, tree: etree._ElementTree):
        self.root = tree.getroot()

    def xpath(self, expr: str, node=None):
        return (node if node is not None else self.root).xpath(expr, namespaces=NS)

    def text(self, expr: str, node=None) -> str:
        found = self.xpath(expr, node)
        if not found:
            return ""
        first = found[0]
        return (first if isinstance(first, str) else (first.text or "")).strip()

    def amount(self, expr: str, node=None) -> Decimal | None:
        return to_decimal(self.text(expr, node))

    def issue_date(self) -> date | None:
        return parse_date(self.text("/*/cbc:IssueDate"))


def to_decimal(text: str) -> Decimal | None:
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def parse_date(text: str) -> date | None:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def fmt(value: Decimal | None) -> str:
    return "missing" if value is None else f"{value:.2f}"


CHECKS: dict[str, Callable[[Invoice, Context], list[Failure]]] = {}


def check(func):
    CHECKS[func.__name__] = func
    return func


# --- CORE (COM-02) ----------------------------------------------------------------------------------------------

@check
def valid_issue_date(inv: Invoice, ctx: Context) -> list[Failure]:
    text = inv.text("/*/cbc:IssueDate")
    return [] if parse_date(text) else [Failure(text)]


@check
def type_code_in_list(inv: Invoice, ctx: Context) -> list[Failure]:
    code = inv.text("/*/cbc:InvoiceTypeCode")
    return [] if code in ctx.code_lists.get("invoice_type", []) else [Failure(code)]


@check
def currency_in_list(inv: Invoice, ctx: Context) -> list[Failure]:
    code = inv.text("/*/cbc:DocumentCurrencyCode")
    return [] if code in ctx.code_lists.get("currency", []) else [Failure(code)]


def _lines(inv: Invoice):
    return inv.xpath("/*/cac:InvoiceLine")


@check
def line_net_amounts(inv: Invoice, ctx: Context) -> list[Failure]:
    failures = []
    for position, line in enumerate(_lines(inv), start=1):
        line_id = inv.text("cbc:ID", line) or str(position)
        quantity = inv.amount("cbc:InvoicedQuantity", line)
        price = inv.amount("cac:Price/cbc:PriceAmount", line)
        base = inv.amount("cac:Price/cbc:BaseQuantity", line) or Decimal(1)
        net = inv.amount("cbc:LineExtensionAmount", line)
        if quantity is None or price is None or net is None or abs(money(quantity * price / base) - net) > TOLERANCE:
            failures.append(Failure(line_id, f"/*/cac:InvoiceLine[{position}]/cbc:LineExtensionAmount"))
    return failures


@check
def sum_of_lines(inv: Invoice, ctx: Context) -> list[Failure]:
    total = inv.amount("/*/cac:LegalMonetaryTotal/cbc:LineExtensionAmount")
    nets = [inv.amount("cbc:LineExtensionAmount", line) for line in _lines(inv)]
    if total is None or None in nets or abs(sum(nets, Decimal(0)) - total) > TOLERANCE:
        return [Failure(fmt(total))]
    return []


def _document_tax_total(inv: Invoice):
    """The TaxTotal in the document currency (Kestria adds a second one in KSK with no subtotals)."""
    currency = inv.text("/*/cbc:DocumentCurrencyCode")
    totals = inv.xpath("/*/cac:TaxTotal")
    for total in totals:
        if inv.text("cbc:TaxAmount/@currencyID", total) == currency:
            return total
    return totals[0] if totals else None


@check
def vat_breakdown(inv: Invoice, ctx: Context) -> list[Failure]:
    total = _document_tax_total(inv)
    if total is None:
        return [Failure("there is no VAT total")]
    failures, subtotal_sum = [], Decimal(0)
    for position, sub in enumerate(inv.xpath("cac:TaxSubtotal", total), start=1):
        taxable = inv.amount("cbc:TaxableAmount", sub)
        tax = inv.amount("cbc:TaxAmount", sub)
        rate = inv.amount("cac:TaxCategory/cbc:Percent", sub)
        where = f"/*/cac:TaxTotal/cac:TaxSubtotal[{position}]/cbc:TaxAmount"
        if taxable is None or tax is None or rate is None:
            failures.append(Failure(f"VAT subtotal {position} lacks a taxable amount, tax amount or rate", where))
            continue
        expected = money(taxable * rate / 100)
        if abs(expected - tax) > TOLERANCE:
            failures.append(Failure(f"subtotal at {rate:g} %: {taxable:.2f} x {rate:g} % = {expected:.2f}, "
                                    f"but the invoice states {tax:.2f}", where))
        subtotal_sum += tax
    stated = inv.amount("cbc:TaxAmount", total)
    if stated is None or abs(subtotal_sum - stated) > TOLERANCE:
        failures.append(Failure(f"the VAT total {fmt(stated)} is not the sum of the subtotals ({subtotal_sum:.2f})",
                                "/*/cac:TaxTotal/cbc:TaxAmount"))
    return failures


@check
def payable_amount(inv: Invoice, ctx: Context) -> list[Failure]:
    totals = "/*/cac:LegalMonetaryTotal/cbc:"
    inclusive = inv.amount(totals + "TaxInclusiveAmount")
    payable = inv.amount(totals + "PayableAmount")
    prepaid = inv.amount(totals + "PrepaidAmount") or Decimal(0)
    rounding = inv.amount(totals + "PayableRoundingAmount") or Decimal(0)
    if inclusive is None or payable is None or abs(inclusive - prepaid + rounding - payable) > TOLERANCE:
        return [Failure(fmt(payable))]
    return []


# --- Valdoria (VD-TS-02) -----------------------------------------------------------------------------------------

def vd_tax_id_valid(tax_id: str) -> bool:
    """VD + nine digits; the ninth is 11 - (weighted sum mod 11) with weights 9..2; 11 -> 0, 10 -> invalid."""
    match = re.fullmatch(r"VD(\d{9})", tax_id)
    if not match:
        return False
    digits = [int(d) for d in match.group(1)]
    check_digit = 11 - sum(d * w for d, w in zip(digits[:8], range(9, 1, -1), strict=True)) % 11
    if check_digit == 10:
        return False
    return digits[8] == (0 if check_digit == 11 else check_digit)


@check
def vd_seller_tax_id(inv: Invoice, ctx: Context) -> list[Failure]:
    tax_id = inv.text(SELLER_TAX_ID)
    return [] if vd_tax_id_valid(tax_id) else [Failure(tax_id)]


@check
def vd_buyer_tax_id(inv: Invoice, ctx: Context) -> list[Failure]:
    tax_id = inv.text(BUYER_TAX_ID)
    return [] if vd_tax_id_valid(tax_id) else [Failure(tax_id)]


@check
def vd_invoice_number_format(inv: Invoice, ctx: Context) -> list[Failure]:
    number = inv.text("/*/cbc:ID")
    match = re.fullmatch(r"[A-Z]{2,4}-(\d{4})-\d{6}", number)
    issued = inv.issue_date()
    if not match or (issued is not None and int(match.group(1)) != issued.year):
        return [Failure(number)]
    return []


@check
def vd_b2b_scope_known(inv: Invoice, ctx: Context) -> list[Failure]:
    return [] if ctx.taxpayer_size in ("large", "other") else [Failure(ctx.taxpayer_size)]


@check
def vd_clearance_id(inv: Invoice, ctx: Context) -> list[Failure]:
    clearance_id = inv.text("/*/cac:AdditionalDocumentReference/cbc:ID[@schemeID = 'VCP']")
    return [] if re.fullmatch(r"VCP-\d{4}-\d{8}", clearance_id) else [Failure(clearance_id)]


# --- Kestria (KS-TS-01, KS-CL-00 / KS-CL-01) ----------------------------------------------------------------------

@check
def ks_seller_tax_id(inv: Invoice, ctx: Context) -> list[Failure]:
    tax_id = inv.text(SELLER_TAX_ID)
    return [] if re.fullmatch(r"KS\d{8}", tax_id) else [Failure(tax_id)]


REDUCED_RATE_CHANGE = date(2026, 3, 1)


def ks_vat_rate(category: str, tax_point: date) -> Decimal | None:
    """The Kestrian rate of a VAT category on a tax point date (KS-CL-01 §1); None for an unknown category."""
    if category == "AA":
        return Decimal(12) if tax_point < REDUCED_RATE_CHANGE else Decimal(10)
    return {"S": Decimal(25), "E": Decimal(0)}.get(category)


@check
def ks_vat_rates(inv: Invoice, ctx: Context) -> list[Failure]:
    stated_tax_point = inv.text("/*/cbc:TaxPointDate")
    tax_point = parse_date(stated_tax_point) if stated_tax_point else inv.issue_date()
    if tax_point is None:
        if stated_tax_point:
            return [Failure(f"The tax point date '{stated_tax_point}' is not a date in the form YYYY-MM-DD.",
                            "/*/cbc:TaxPointDate")]
        return []  # CORE-02 reports the bad issue date
    total = _document_tax_total(inv)
    subtotals = inv.xpath("cac:TaxSubtotal", total) if total is not None else []
    failures = []
    for position, sub in enumerate(subtotals, start=1):
        category = inv.text("cac:TaxCategory/cbc:ID", sub)
        rate = inv.amount("cac:TaxCategory/cbc:Percent", sub)
        expected = ks_vat_rate(category, tax_point)
        where = f"/*/cac:TaxTotal/cac:TaxSubtotal[{position}]/cac:TaxCategory/cbc:Percent"
        if expected is None:
            failures.append(Failure(f"VAT category '{category}' is not in the Kestrian VAT code list "
                                    "(S, AA or E).", where))
        elif rate is None or rate != expected:
            stated = "no" if rate is None else f"a {rate:g} %"
            failures.append(Failure(f"VAT category {category} has {stated} rate, but on "
                                    f"{tax_point.isoformat()} the rate is {expected:g} %.", where))
    return failures


# --- Orlavia (OL-TS-01) ------------------------------------------------------------------------------------------

@check
def ol_seller_tax_id(inv: Invoice, ctx: Context) -> list[Failure]:
    tax_id = inv.text(SELLER_TAX_ID)
    return [] if re.fullmatch(r"OL\d{10}", tax_id) else [Failure(tax_id)]


def ol_qr_fields(inv: Invoice) -> list[str]:
    """The six data fields of the ORTS QR payload, taken from the invoice (OL-TS-01 §4)."""
    total = inv.amount("/*/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount")
    return [inv.text(SELLER_TAX_ID), inv.text("/*/cbc:ID"), inv.text("/*/cbc:IssueDate"),
            inv.text("/*/cbc:IssueTime"), "" if total is None else f"{money(total):.2f}",
            inv.text("/*/cbc:DocumentCurrencyCode")]


def ol_qr_digest(fields: list[str]) -> str:
    return hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()[:16]


def ol_qr_payload(fields: list[str]) -> str:
    return "|".join(["ORTS1", *fields, ol_qr_digest(fields)])


QR_FIELD_NAMES = ["seller tax ID", "invoice number", "issue date", "issue time", "total with VAT", "currency"]


@check
def ol_qr_hash(inv: Invoice, ctx: Context) -> list[Failure]:
    payload = inv.text("/*/cac:AdditionalDocumentReference/cbc:ID[@schemeID = 'ORTS-QR']")
    if not payload:
        return []  # OL-02 reports a missing payload
    parts = payload.split("|")
    if len(parts) != 8 or parts[0] != "ORTS1":
        return [Failure("the payload does not have the 8 fields 'ORTS1|...|hash'")]
    expected = ol_qr_fields(inv)
    differing = [name for name, got, want in zip(QR_FIELD_NAMES, parts[1:7], expected, strict=True) if got != want]
    if differing:
        return [Failure(f"{', '.join(differing)} in the payload differ from the invoice")]
    if parts[7] != ol_qr_digest(expected):
        return [Failure("the hash is not the SHA-256 of the payload fields")]
    return []

