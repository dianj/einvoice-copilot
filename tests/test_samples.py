"""The generated sample invoices: each yields exactly its expected findings, and together they test every rule."""
import json
from collections import defaultdict

import pytest

from copilot import config
from copilot.rules.definitions import rules
from copilot.rules.engine import validate
from samples.generator import INJECTION, write_all

SAMPLES = sorted(p.name.removesuffix(".expected.json") for p in config.SAMPLES_DIR.glob("*.expected.json"))


def load(name):
    expected = json.loads((config.SAMPLES_DIR / f"{name}.expected.json").read_text(encoding="utf-8"))
    return (config.SAMPLES_DIR / f"{name}.xml").read_bytes(), expected


def run(name):
    data, expected = load(name)
    return validate(data, **expected["params"]), expected


def test_there_are_enough_samples():
    valid = [n for n in SAMPLES if not load(n)[1]["expected_rule_ids"]]
    assert len(SAMPLES) >= 30 and len(valid) >= 10


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_yields_exactly_its_expected_findings(name):
    report, expected = run(name)
    assert sorted(f.rule_id for f in report.findings) == expected["expected_rule_ids"]
    assert report.valid == all(rule_id == "VD-06" for rule_id in expected["expected_rule_ids"])  # VD-06 = warning


def test_every_rule_fails_in_one_sample_and_passes_in_another():
    """Each of the rules is reported by at least one sample and checked without a finding in at least one other."""
    failed, passed = defaultdict(list), defaultdict(list)
    for name in SAMPLES:
        report, _ = run(name)
        reported = {f.rule_id for f in report.findings}
        for rule_id in report.rules_checked:
            (failed if rule_id in reported else passed)[rule_id].append(name)
    all_ids = {r.id for r in rules().all}
    assert {r for r in all_ids if not failed[r]} == set()
    assert {r for r in all_ids if not passed[r]} == set()


def test_generator_is_deterministic(tmp_path):
    write_all(seed=7, out_dir=tmp_path)
    fresh = {p.name: p.read_bytes() for p in (tmp_path / "invoices").iterdir()}
    committed = {p.name: p.read_bytes() for p in config.SAMPLES_DIR.iterdir()}
    assert fresh == committed, "samples/invoices is stale: run python samples/generator.py --seed 7"


def test_the_pre_approved_note_changes_nothing():
    data, expected = load("ks-demo-old-rate-no-ksk-total")
    assert INJECTION.encode() in data
    without_note = data.replace(f"<cbc:Note>{INJECTION}</cbc:Note>".encode(), b"")
    assert without_note != data
    with_note, plain = validate(data), validate(without_note)
    assert not with_note.valid and with_note.findings == plain.findings
