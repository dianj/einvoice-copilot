"""Load the corpus: Markdown documents with YAML front matter, split into numbered `##` sections.

Two time axes (ARCHITECTURE.md §3.3): `valid_from` / `valid_to` say when this *version* of a document is the current
one (the retrieval filter uses them); `announces` lists the obligation dates the text talks about, which may lie in
the future of the document's own validity.
"""
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from copilot import config

COUNTRIES = ("VD", "KS", "OL", "COMMON")
FOLDERS = {"common": "COMMON", "valdoria": "VD", "kestria": "KS", "orlavia": "OL"}
RULE_ID = re.compile(r"\b(?:CORE|VD|KS|OL)-\d{2}\b")
SECTION = re.compile(r"^## +(\d+)\. +(.+)$", re.M)


class Section(BaseModel):
    number: int
    heading: str
    text: str

    @property
    def ref(self) -> str:
        return f"§{self.number}"


class Document(BaseModel):
    doc_id: str = Field(pattern=r"^(COM|VD|KS|OL|TEST)-[A-Z]*-?\d{2}$")
    title: str
    country: Literal["VD", "KS", "OL", "COMMON"]
    doc_type: Literal["law", "technical_spec", "faq", "amendment", "code_list", "guide", "glossary"]
    version: str
    published: date
    valid_from: date
    valid_to: date | None = None
    announces: list[date] = []
    supersedes: list[str] = []
    authority: Literal[1, 2, 3]
    lang: str
    test_only: bool = False
    body: str = ""
    sections: list[Section] = []

    @field_validator("version", mode="before")
    @classmethod
    def version_as_text(cls, value):
        return str(value)

    @model_validator(mode="after")
    def check_dates(self):
        if self.valid_from < self.published:
            raise ValueError(f"{self.doc_id}: valid_from is before the publication date")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(f"{self.doc_id}: valid_to is before valid_from")
        return self

    def valid_on(self, day: date) -> bool:
        return self.valid_from <= day and (self.valid_to is None or day <= self.valid_to)

    def section(self, number: int) -> Section | None:
        return next((s for s in self.sections if s.number == number), None)

    @property
    def rule_ids(self) -> set[str]:
        return set(RULE_ID.findall(self.body))


def parse_document(text: str, source: str = "") -> Document:
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text.lstrip("﻿"), re.S)
    if not match:
        raise ValueError(f"{source}: no front matter")
    fields = yaml.safe_load(match.group(1)) or {}
    body = match.group(2)
    parts = SECTION.split(body)
    # parts = [text before the first section, number, heading, text, number, heading, text, ...]
    sections = [Section(number=int(n), heading=h.strip(), text=t.strip())
                for n, h, t in zip(parts[1::3], parts[2::3], parts[3::3], strict=True)]
    return Document(**fields, body=body, sections=sections)


def load_corpus(corpus_dir: Path = None, include_test: bool = None) -> list[Document]:
    corpus_dir = corpus_dir or config.CORPUS_DIR
    include_test = config.CORPUS_INCLUDE_TEST if include_test is None else include_test
    docs = []
    for folder, country in FOLDERS.items():
        for path in sorted((corpus_dir / folder).glob("*.md")):
            doc = parse_document(path.read_text(encoding="utf-8"), str(path))
            if doc.country != country:
                raise ValueError(f"{path}: country {doc.country} does not match the folder '{folder}'")
            if doc.test_only:
                raise ValueError(f"{path}: test-only documents belong in corpus/test-only")
            docs.append(doc)
    if include_test:
        docs += [parse_document(p.read_text(encoding="utf-8"), str(p))
                 for p in sorted((corpus_dir / "test-only").glob("*.md"))]
    ids = [d.doc_id for d in docs]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate doc_id: {sorted(duplicates)}")
    return docs


@lru_cache(maxsize=2)
def corpus(include_test: bool = False) -> tuple[Document, ...]:
    """The corpus, loaded once per process."""
    return tuple(load_corpus(include_test=include_test))


def load_facts(corpus_dir: Path = None) -> dict:
    return yaml.safe_load(((corpus_dir or config.CORPUS_DIR) / "facts.yaml").read_text(encoding="utf-8"))
