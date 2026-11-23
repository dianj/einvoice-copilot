"""The deterministic validation engine: parse safely, work out the context, run the applicable rules, report.

Validity comes only from here; the LLM (from E3) explains this report and may not change it.
"""
import hashlib
import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel

from copilot import config
from copilot.rules.checks import BUYER_TAX_ID, CHECKS, SELLER_TAX_ID, Context, Invoice
from copilot.rules.definitions import Rule, Rules, rules
from copilot.rules.parsing import NS, InvoiceXMLError, parse_invoice

log = logging.getLogger("copilot.rules")

Country = Literal["VD", "KS", "OL"]
TransactionType = Literal["B2B", "B2G", "B2C"]
Stage = Literal["pre_clearance", "cleared"]
TaxpayerSize = Literal["large", "other", "unknown"]
MAX_VALUE_CHARS = 200


class Finding(BaseModel):
    rule_id: str
    severity: Literal["error", "warning"]
    title: str
    location: str
    value: str
    message: str
    fix_hint: str
    doc_ref: list[str]


class ValidationReport(BaseModel):
    country: Country | None
    transaction_type: TransactionType | None
    stage: Stage
    taxpayer_size: TaxpayerSize
    issue_date: date | None
    rule_date: date | None          # the date used to select the rules
    rules_checked: list[str]
    findings: list[Finding]
    notes: list[str]
    valid: bool
    rule_set_version: str


def rule_set_version() -> str:
    """A short fingerprint of the rule files, so a report says exactly which rules produced it."""
    digest = hashlib.sha256()
    for path in sorted(config.RULES_DIR.glob("*.yaml")):
        digest.update(path.read_bytes())
    return f"cim-1.0+{digest.hexdigest()[:10]}"


def detect_country(inv: Invoice) -> Country | None:
    prefix = inv.text(SELLER_TAX_ID)[:2].upper()
    return prefix if prefix in ("VD", "KS", "OL") else None


def detect_transaction_type(inv: Invoice) -> TransactionType:
    """B2B when the buyer has a tax ID, B2C when not. UBL does not say whether a buyer is a public body, so B2G
    is only ever chosen by the caller."""
    return "B2B" if inv.text(BUYER_TAX_ID) else "B2C"


def run_rule(rule: Rule, inv: Invoice, ctx: Context) -> list[Finding]:
    if rule.check_type == "xpath":
        passed = bool(inv.root.xpath(f"boolean({rule.check_body})", namespaces=NS))
        failures = [] if passed else [(inv.text(rule.location), None)]
    else:
        failures = CHECKS[rule.check_body](inv, ctx)
    findings = []
    for value, location in failures:
        value = value[:MAX_VALUE_CHARS]
        findings.append(Finding(rule_id=rule.id, severity=rule.severity, title=rule.title,
                                location=location or rule.location, value=value,
                                message=rule.message.replace("{value}", value), fix_hint=rule.fix_hint,
                                doc_ref=rule.doc_ref))
    return findings


def xml_error_report(reason: str, stage: str, taxpayer_size: str) -> ValidationReport:
    finding = Finding(rule_id="XML-00", severity="error", title="The file is a readable UBL 2.1 invoice",
                      location="/", value="", message=reason,
                      fix_hint="Upload a well-formed UBL 2.1 Invoice document without a DOCTYPE.", doc_ref=[])
    return ValidationReport(country=None, transaction_type=None, stage=stage, taxpayer_size=taxpayer_size,
                            issue_date=None, rule_date=None, rules_checked=[], findings=[finding], notes=[],
                            valid=False, rule_set_version=rule_set_version())


def validate(data: bytes, country: Country | None = None, transaction_type: TransactionType | None = None,
             stage: Stage = "pre_clearance", taxpayer_size: TaxpayerSize = "unknown",
             rule_set: Rules | None = None) -> ValidationReport:
    """Validate one UBL invoice. Parameters left out are worked out from the invoice (see the notes in the report).

    Anything in the invoice text, such as a `cbc:Note` that claims the invoice is pre-approved, is data and
    changes nothing here.
    """
    try:
        tree = parse_invoice(data, config.MAX_UPLOAD_KB)
    except InvoiceXMLError as exc:
        return xml_error_report(str(exc), stage, taxpayer_size)
    rule_set = rule_set or rules()
    inv, notes = Invoice(tree), []

    if country is None:
        country = detect_country(inv)
        notes.append(f"Country {country} from the seller tax ID prefix." if country else
                     "The country could not be told from the seller tax ID: only the common (CORE) rules were "
                     "checked. Choose the country to check its rules too.")
    if transaction_type is None:
        transaction_type = detect_transaction_type(inv)
        notes.append(f"Transaction type {transaction_type} from the buyer data "
                     f"({'buyer tax ID present' if transaction_type == 'B2B' else 'no buyer tax ID'}); "
                     "choose B2G for a public-sector buyer.")

    issue_date = inv.issue_date()
    rule_date = issue_date or config.today()
    if issue_date is None:
        notes.append(f"The issue date is not valid, so the rules in force on {rule_date.isoformat()} (today) "
                     "were used.")

    ctx = Context(country=country, transaction_type=transaction_type, stage=stage, taxpayer_size=taxpayer_size,
                  code_lists={name: rule_set.code_list(name, country or "CORE")
                              for name in rule_set.sets["CORE"].code_lists})
    selected = rule_set.applicable(country or "CORE", transaction_type, rule_date, stage)
    findings = [f for rule in selected for f in run_rule(rule, inv, ctx)]
    log.info("validated %s: %s %s %s, %d rules, %d findings", inv.text("/*/cbc:ID") or "(no number)", country,
             transaction_type, rule_date, len(selected), len(findings))
    return ValidationReport(country=country, transaction_type=transaction_type, stage=stage,
                            taxpayer_size=taxpayer_size, issue_date=issue_date, rule_date=rule_date,
                            rules_checked=[r.id for r in selected], findings=findings, notes=notes,
                            valid=not any(f.severity == "error" for f in findings),
                            rule_set_version=rule_set_version())

