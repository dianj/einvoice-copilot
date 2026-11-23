"""The engine as a whole: safe parsing, context detection, rule selection and the report."""
import json
import re
import time

import pytest

from copilot import config
from copilot.rules.engine import rule_set_version, validate
from samples.generator import NS, Party, Templates, build, edit, etree


def xml(spec) -> bytes:
    return etree.tostring(build(spec), xml_declaration=True, encoding="UTF-8")


@pytest.fixture
def t():
    return Templates(seed=3)


def ids(report):
    return sorted(f.rule_id for f in report.findings)


# --- XML safety ---------------------------------------------------------------------------------------------------

def only_xml_00(report):
    assert ids(report) == ["XML-00"] and not report.valid and report.rules_checked == []
    return report.findings[0].message


def test_external_entity_does_not_read_local_files(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-CONTENT")
    data = (f'<?xml version="1.0"?><!DOCTYPE Invoice [<!ENTITY x SYSTEM "{secret.as_uri()}">]>'
            f'<Invoice xmlns="{NS["inv"]}" xmlns:cbc="{NS["cbc"]}"><cbc:ID>&x;</cbc:ID></Invoice>').encode()
    report = validate(data)
    assert "DOCTYPE" in only_xml_00(report) and "TOP-SECRET" not in report.model_dump_json()


def test_billion_laughs_is_refused_quickly():
    entities = '<!ENTITY a0 "lol">' + "".join(f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10))
    data = f'<?xml version="1.0"?><!DOCTYPE Invoice [{entities}]><Invoice xmlns="{NS["inv"]}">&a9;</Invoice>'
    started = time.perf_counter()
    # Refused either by libxml2's amplification limit or by the DOCTYPE check; never expanded.
    assert re.search("amplification|DOCTYPE", only_xml_00(validate(data.encode())))
    assert time.perf_counter() - started < 1


def test_a_doctype_hidden_in_utf16_is_still_refused():
    data = f'<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE Invoice><Invoice xmlns="{NS["inv"]}"/>'
    assert "DOCTYPE" in only_xml_00(validate(data.encode("utf-16")))


@pytest.mark.parametrize("data, reason", [
    (b"<Invoice", "not well-formed"),
    (b"", "not well-formed"),
    (b'<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"/>', "not 'CreditNote'"),
    (b"<Invoice/>", "must be a UBL 2.1 Invoice"),
])
def test_unreadable_files_give_one_xml_00_finding(data, reason):
    assert reason in only_xml_00(validate(data))


def test_size_limit(monkeypatch, t):
    monkeypatch.setattr(config, "MAX_UPLOAD_KB", 1)
    assert "larger than 1 KB" in only_xml_00(validate(xml(t.kestria())))


# --- Context --------------------------------------------------------------------------------------------------------

def test_country_and_transaction_type_from_the_invoice(t):
    report = validate(xml(t.kestria()))
    assert (report.country, report.transaction_type, report.valid) == ("KS", "B2B", True)
    assert report.notes[0] == "Country KS from the seller tax ID prefix."
    assert "KS-01" in report.rules_checked and not any(r.startswith(("VD", "OL")) for r in report.rules_checked)

    consumer = validate(xml(edit(t.orlavia(), buyer=Party("Ana Velis", None))))
    assert consumer.transaction_type == "B2C" and "no buyer tax ID" in consumer.notes[1]


def test_explicit_parameters_win_and_add_no_notes(t):
    report = validate(xml(t.kestria()), country="KS", transaction_type="B2G")
    assert report.transaction_type == "B2G" and report.notes == [] and ids(report) == ["KS-06"]


def test_unknown_country_checks_only_core_rules(t):
    spec = edit(t.kestria(), seller=Party("Nowhere Ltd", "XX12345678", endpoint="e"))
    report = validate(xml(spec))
    assert report.country is None and report.valid
    assert report.rules_checked and all(r.startswith("CORE-") for r in report.rules_checked)
    assert "only the common (CORE) rules" in report.notes[0]


def test_rules_are_chosen_by_the_issue_date(t):
    spec = t.valdoria("2026-04-01")                                   # transition period: VD-06 applies
    assert "VD-06" in validate(xml(spec)).rules_checked
    assert "VD-06" not in validate(xml(t.valdoria("2026-07-01"))).rules_checked
    assert validate(xml(spec), taxpayer_size="large").findings == []
    assert "VD-09" in validate(xml(spec), stage="cleared").rules_checked


def test_a_bad_issue_date_falls_back_to_today(t):
    report = validate(xml(edit(t.kestria(), issue_date="2026-02-30")))
    assert report.issue_date is None and report.rule_date.isoformat() == config.FROZEN_TODAY
    assert ids(report) == ["CORE-02"] and "(today)" in report.notes[-1]


def test_a_warning_alone_keeps_the_invoice_valid(t):
    report = validate(xml(t.valdoria("2026-04-01")))
    assert ids(report) == ["VD-06"] and report.findings[0].severity == "warning" and report.valid


def test_finding_fields_and_value_in_the_message(t):
    report = validate(xml(edit(t.valdoria(), seller=Party("Arvenna Tools Ltd", "VD123456780"))))
    finding = report.findings[0]
    assert finding.model_dump() == {
        "rule_id": "VD-01", "severity": "error", "title": "Seller tax ID is a valid Valdorian tax ID",
        "location": "/*/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
        "value": "VD123456780",
        "message": "Seller tax ID 'VD123456780' is not a valid Valdorian tax ID (VD + nine digits, mod-11 check "
                   "digit).",
        "fix_hint": "Use the tax ID registered with the Valdorian Revenue Office; the check digit is computed as in "
                    "VD-TS-02 §4.",
        "doc_ref": ["VD-TS-02 §4"]}


def test_long_values_are_cut(t):
    report = validate(xml(edit(t.valdoria(), number="X" * 5000)))
    assert len(report.findings[0].value) == 200


def test_xpath_rule_reports_the_value_at_its_location(t):
    report = validate(xml(edit(t.kestria(), currency="EUR", ksk_rate=None, tax_currency="SEK")))
    values = {f.rule_id: f.value for f in report.findings}
    # KS-04's location is the VAT total, so its value is the amount in the document currency.
    assert values["KS-03"] == "SEK" and set(values) == {"KS-03", "KS-04"}
    assert re.fullmatch(r"\d+\.\d{2}", values["KS-04"])


def test_rule_set_version_changes_with_the_rules(tmp_path, monkeypatch):
    before = rule_set_version()
    for path in config.RULES_DIR.glob("*.yaml"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    monkeypatch.setattr(config, "RULES_DIR", tmp_path)
    assert rule_set_version() == before
    (tmp_path / "core.yaml").write_text((tmp_path / "core.yaml").read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert rule_set_version() != before and before.startswith("cim-1.0+")


def test_report_is_json_serialisable(t):
    json.loads(validate(xml(t.orlavia())).model_dump_json())
