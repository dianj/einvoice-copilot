"""Rule definitions: schema, XPath syntax, code lists and rule selection by country, type, date and stage."""
from datetime import date

import pytest
import yaml
from lxml import etree

from copilot import config
from copilot.rules.definitions import Rule, RuleSet, load_rules

RULES = load_rules()
UBL_NS = {"cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
          "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"}


def ids(rules):
    return {r.id for r in rules}


def test_e2_scope_of_about_thirty_rules():
    counts = {country: len(s.rules) for country, s in RULES.sets.items()}
    assert counts == {"CORE": 12, "VD": 7, "KS": 6, "OL": 5}


@pytest.mark.parametrize("rule_id", sorted(r.id for r in RULES.all if r.check_type == "xpath"))
def test_xpath_checks_compile(rule_id):
    etree.XPath(RULES.get(rule_id).check_body, namespaces=UBL_NS)


def test_python_checks_name_a_function():
    for rule in RULES.all:
        if rule.check_type == "python":
            assert rule.check_body.isidentifier(), rule.id


def test_code_lists_are_extended_per_country_never_reduced():
    assert RULES.code_list("invoice_type", "VD") == ["380", "381"]
    assert RULES.code_list("invoice_type", "OL") == ["380", "381", "389"]
    assert "KSK" in RULES.code_list("currency", "KS") and "EUR" in RULES.code_list("currency", "OL")


def test_clearance_rules_apply_only_to_cleared_valdorian_invoices_from_2026():
    before = ids(RULES.applicable("VD", "B2B", date(2025, 12, 31), "cleared"))
    pre = ids(RULES.applicable("VD", "B2B", date(2026, 1, 1), "pre_clearance"))
    cleared = ids(RULES.applicable("VD", "B2B", date(2026, 1, 1), "cleared"))
    assert "VD-09" not in before and "VD-09" not in pre and {"VD-05", "VD-09"} <= cleared


def test_the_transition_scope_warning_only_runs_until_30_june_2026():
    assert "VD-06" in ids(RULES.applicable("VD", "B2B", date(2026, 6, 30)))
    assert "VD-06" not in ids(RULES.applicable("VD", "B2B", date(2026, 7, 1)))
    assert RULES.get("VD-06").severity == "warning"


def test_rules_by_transaction_type_and_country():
    b2g = ids(RULES.applicable("KS", "B2G", date(2026, 5, 1)))
    assert "KS-06" in b2g and "KS-06" not in ids(RULES.applicable("KS", "B2B", date(2026, 5, 1)))
    assert not any(i.startswith(("VD-", "OL-")) for i in b2g) and "CORE-01" in b2g
    assert "OL-04" not in ids(RULES.applicable("OL", "B2C", date(2026, 5, 1)))  # no self-billing to consumers
    assert "VD-02" not in ids(RULES.applicable("VD", "B2G", date(2026, 5, 1)))


def test_invalid_definitions_are_rejected():
    base = RULES.get("KS-06").model_dump(exclude={"country"})
    with pytest.raises(ValueError, match="check must start"):
        Rule(**{**base, "check": "regex:.*"})
    with pytest.raises(ValueError, match="doc_ref"):
        Rule(**{**base, "doc_ref": ["KS-TS-01 section 6"]})
    with pytest.raises(ValueError, match="effective_to is before"):
        Rule(**{**base, "effective_to": date(2020, 1, 1)})
    with pytest.raises(ValueError, match="is in the VD rule set"):
        RuleSet(country="VD", rules=[base])


def test_duplicate_ids_and_a_missing_core_set_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="core.yaml is missing"):
        load_rules(tmp_path)
    core = yaml.safe_load((config.RULES_DIR / "core.yaml").read_text(encoding="utf-8"))
    (tmp_path / "core.yaml").write_text(yaml.safe_dump(core), encoding="utf-8")
    # A second file for the same country replaces the first; a VD set reusing a VD id twice is a duplicate.
    vd = {"country": "VD", "rules": [RULES.get("VD-01").model_dump(exclude={"country"}, mode="json")] * 2}
    (tmp_path / "valdoria.yaml").write_text(yaml.safe_dump(vd), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate rule ids"):
        load_rules(tmp_path)
