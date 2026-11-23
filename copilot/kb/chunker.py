"""Split documents into retrieval chunks: one per `##` section, long sections split by paragraph with overlap.

The embedder reads about 128 tokens, so a chunk stays under ~600 characters. Dates go into the metadata as integers
YYYYMMDD (Chroma range filters accept numbers only, and metadata cannot be null: an open end is 99991231).
"""
import hashlib
from datetime import date

from pydantic import BaseModel

from copilot.corpus.loader import RULE_ID, Document

MAX_CHARS = 600
OVERLAP_CHARS = 100
OPEN_END = 99991231


def date_int(day: date | None) -> int:
    return OPEN_END if day is None else day.year * 10000 + day.month * 100 + day.day


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    country: str
    doc_type: str
    authority: int
    published: date
    valid_from: date
    valid_to: date | None
    test_only: bool
    section: int
    heading: str
    chunk_no: int
    text: str

    @property
    def ref(self) -> str:
        return f"{self.doc_id} §{self.section}"

    @property
    def rule_ids(self) -> list[str]:
        return sorted(set(RULE_ID.findall(self.text)))

    @property
    def embed_text(self) -> str:
        return f"{self.title}. {self.heading}\n{self.text}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    def metadata(self) -> dict:
        """Flat metadata for the vector store (no nulls, dates as integers)."""
        return {"doc_id": self.doc_id, "country": self.country, "doc_type": self.doc_type,
                "authority": self.authority, "published": date_int(self.published),
                "valid_from": date_int(self.valid_from), "valid_to": date_int(self.valid_to),
                "test_only": self.test_only, "section": self.section, "chunk_no": self.chunk_no,
                "rule_ids": ",".join(self.rule_ids), "hash": self.content_hash}


def split_text(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[str]:
    """Paragraph-sized pieces of at most `max_chars`; each piece after the first starts with the end of the previous."""
    if len(text) <= max_chars:
        return [text]
    limit = max_chars - overlap - 1          # so that the overlap + a newline + one unit still fit
    units = []
    for paragraph in [p.strip() for p in text.split("\n") if p.strip()]:
        while len(paragraph) > limit:      # a very long line: cut at the last space before the limit
            cut = paragraph.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            units.append(paragraph[:cut])
            paragraph = paragraph[cut:].strip()
        units.append(paragraph)
    pieces, current = [], ""
    for unit in units:
        if current and len(current) + 1 + len(unit) > max_chars:
            pieces.append(current)
            tail = current[-overlap:]
            current = tail[tail.find(" ") + 1:] if " " in tail else tail
        current = f"{current}\n{unit}" if current else unit
    pieces.append(current)
    return pieces


def chunk_document(doc: Document) -> list[Chunk]:
    chunks = []
    for section in doc.sections:
        for number, text in enumerate(split_text(section.text)):
            chunks.append(Chunk(chunk_id=f"{doc.doc_id}#{section.number}.{number}", doc_id=doc.doc_id,
                                title=doc.title, country=doc.country, doc_type=doc.doc_type,
                                authority=doc.authority, published=doc.published, valid_from=doc.valid_from,
                                valid_to=doc.valid_to, test_only=doc.test_only, section=section.number,
                                heading=section.heading, chunk_no=number, text=text))
    return chunks
