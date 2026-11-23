"""Rule definitions: load `rules/*.yaml`, validate them, merge code lists and select the rules that apply.

A rule applies to an invoice when its country is CORE or the invoice's country, the transaction type is in
`applies_to`, the invoice date is inside the rule's effective range and, for stage-bound rules, the stage matches.
Country rule sets may extend CORE code lists, never remove from them.
"""
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from copilot import config

TransactionType = Literal["B2B", "B2G", "B2C"]
Stage = Literal["pre_clearance", "cleared"]
DOC_REF = re.compile(r"^(?P<doc>[A-Z]+(?:-[A-Z]+)?-\d{2}) §(?P<section>\d+)$")


class Rule(BaseModel):
    id: str = Field(pattern=r"^(CORE|VD|KS|OL)-\d{2}$")
    country: str = ""                       # filled from the rule set
    title: str
    severity: Literal["error", "warning"]
    applies_to: list[TransactionType]
    stages: list[Stage] = ["pre_clearance", "cleared"]
    effective_from: date
    effective_to: date | None = None
    check: str
    location: str
    message: str
    fix_hint: str
    doc_ref: list[str]
    internal: bool = False                  # not described in any document (none so far)

    @field_validator("check")
    @classmethod
    def known_check_type(cls, value):
        if not value.startswith(("xpath:", "python:")):
            raise ValueError("check must start with 'xpath:' or 'python:'")
        return value

    @field_validator("doc_ref")
    @classmethod
    def doc_ref_format(cls, refs):
        for ref in refs:
            if not DOC_REF.match(ref):
                raise ValueError(f"doc_ref '{ref}' must look like 'VD-TS-02 §4'")
        return refs

    @model_validator(mode="after")
    def check_range(self):
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError(f"{self.id}: effective_to is before effective_from")
        return self

    @property
    def check_type(self) -> str:
        return self.check.split(":", 1)[0]

    @property
    def check_body(self) -> str:
        return self.check.split(":", 1)[1].strip()

    def effective_on(self, day: date) -> bool:
        return self.effective_from <= day and (self.effective_to is None or day <= self.effective_to)


class RuleSet(BaseModel):
    country: Literal["CORE", "VD", "KS", "OL"]
    code_lists: dict[str, list[str]] = {}
    rules: list[Rule]

    @model_validator(mode="after")
    def rules_belong_to_the_set(self):
        for rule in self.rules:
            if not rule.id.startswith(f"{self.country}-"):
                raise ValueError(f"rule {rule.id} is in the {self.country} rule set")
            rule.country = self.country
        return self


class Rules(BaseModel):
    sets: dict[str, RuleSet]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [r.id for s in self.sets.values() for r in s.rules]
        duplicates = {i for i in ids if ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate rule ids: {sorted(duplicates)}")
        return self

    @property
    def all(self) -> list[Rule]:
        return [r for s in self.sets.values() for r in s.rules]

    def get(self, rule_id: str) -> Rule | None:
        return next((r for r in self.all if r.id == rule_id), None)

    def code_list(self, name: str, country: str) -> list[str]:
        """CORE's list plus the country's extensions."""
        core = self.sets["CORE"].code_lists.get(name, [])
        extra = self.sets[country].code_lists.get(name, []) if country in self.sets else []
        return core + [code for code in extra if code not in core]

    def applicable(self, country: str, transaction_type: str, day: date, stage: str = "pre_clearance") -> list[Rule]:
        return [r for r in self.all
                if r.country in ("CORE", country) and transaction_type in r.applies_to and r.effective_on(day)
                and stage in r.stages]


def load_rules(rules_dir: Path = None) -> Rules:
    rules_dir = rules_dir or config.RULES_DIR
    sets = {}
    for path in sorted(rules_dir.glob("*.yaml")):
        rule_set = RuleSet(**yaml.safe_load(path.read_text(encoding="utf-8")))
        sets[rule_set.country] = rule_set
    if "CORE" not in sets:
        raise ValueError("rules/core.yaml is missing")
    return Rules(sets=sets)


@lru_cache(maxsize=1)
def rules() -> Rules:
    return load_rules()
