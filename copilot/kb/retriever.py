"""Date-aware hybrid retrieval over the regulation corpus.

1. **Version filter:** only chunks of document versions in force on `as_of` (`valid_from <= as_of <= valid_to`), in
   the Chroma query and again in Python on real dates (defence in depth). Obligation dates a document *announces*
   are never used to filter, so an amendment published in March that moves an obligation to July is found for a
   question about June.
2. **Hybrid ranking:** vector search and BM25 (rule ids, codes such as "381" or "KSK" are exact tokens), fused with
   reciprocal rank fusion.
3. **Abstention:** the question counts as answerable when the best vector similarity reaches the embedder's
   calibrated `min_score`; otherwise the answer is "not in the documents".
"""
import asyncio
import logging
import re
from datetime import date
from functools import lru_cache

from pydantic import BaseModel
from rank_bm25 import BM25Okapi

from copilot import config
from copilot.corpus.loader import corpus
from copilot.kb.chunker import Chunk, chunk_document, date_int
from copilot.kb.embedder import Embedder, make_embedder
from copilot.kb.store import VectorIndex

log = logging.getLogger("copilot.kb")
RRF_K = 60
CANDIDATES = 20
TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
STOPWORDS = {"the", "a", "an", "of", "in", "on", "to", "for", "and", "or", "is", "are", "be", "by", "with", "what",
             "which", "when", "how", "does", "do", "must", "from", "that", "this", "it", "as", "at", "can"}


def tokens(text: str) -> list[str]:
    """Lowercase words; a compound such as 'vd-09' is kept whole and also split, so both spellings match."""
    out = []
    for token in TOKEN.findall(text.lower()):
        if token in STOPWORDS:
            continue
        out.append(token)
        if "-" in token:
            out.extend(part for part in token.split("-") if part not in STOPWORDS)
    return out


class Passage(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    country: str
    doc_type: str
    authority: int
    published: date
    valid_from: date
    valid_to: date | None
    section: int
    heading: str
    text: str
    vector_score: float | None      # cosine similarity, when the vector search found it
    fused_score: float

    @property
    def ref(self) -> str:
        return f"{self.doc_id} §{self.section}"


class SearchResult(BaseModel):
    query: str
    as_of: date
    passages: list[Passage]
    answerable: bool
    top_vector_score: float
    min_score: float


class Retriever:
    def __init__(self, chunks: list[Chunk], embedder: Embedder, index_path=None, include_test: bool = False):
        self.chunks = {c.chunk_id: c for c in chunks}
        self.embedder = embedder
        self.index = VectorIndex(index_path, embedder, include_test)
        self.index.sync(chunks)
        self._ids = list(self.chunks)
        self._bm25 = BM25Okapi([tokens(self.chunks[cid].embed_text) for cid in self._ids])

    @staticmethod
    def allowed(chunk: Chunk, as_of: date, countries: set[str] | None, doc_types: set[str] | None,
                include_test: bool) -> bool:
        if not (chunk.valid_from <= as_of and (chunk.valid_to is None or as_of <= chunk.valid_to)):
            return False
        if chunk.test_only and not include_test:
            return False
        if countries and chunk.country not in countries | {"COMMON"}:
            return False
        return not doc_types or chunk.doc_type in doc_types

    @staticmethod
    def where(as_of: date, countries: set[str] | None, doc_types: set[str] | None, include_test: bool) -> dict:
        day = date_int(as_of)
        clauses = [{"valid_from": {"$lte": day}}, {"valid_to": {"$gte": day}}]
        if not include_test:
            clauses.append({"test_only": False})
        if countries:
            clauses.append({"country": {"$in": sorted(countries | {"COMMON"})}})
        if doc_types:
            clauses.append({"doc_type": {"$in": sorted(doc_types)}})
        return {"$and": clauses}

    def search_sync(self, query: str, as_of: date, countries: set[str] | None = None,
                    doc_types: set[str] | None = None, k: int = 6, include_test: bool = False,
                    hybrid: bool | None = None) -> SearchResult:
        hybrid = config.HYBRID_SEARCH if hybrid is None else hybrid

        def ok(cid):
            return self.allowed(self.chunks[cid], as_of, countries, doc_types, include_test)

        vector_hits = [(cid, score) for cid, score in
                       self.index.query(query, self.where(as_of, countries, doc_types, include_test), CANDIDATES)
                       if ok(cid)]  # the post-filter: never trust the store's filter alone
        vector_scores = dict(vector_hits)
        fused: dict[str, float] = {}
        for rank, (cid, _) in enumerate(vector_hits):
            fused[cid] = fused.get(cid, 0) + 1 / (RRF_K + rank + 1)
        if hybrid:
            scores = self._bm25.get_scores(tokens(query))
            keyword_hits = sorted(((cid, s) for cid, s in zip(self._ids, scores, strict=True) if s > 0 and ok(cid)),
                                  key=lambda hit: -hit[1])[:CANDIDATES]
            for rank, (cid, _) in enumerate(keyword_hits):
                fused[cid] = fused.get(cid, 0) + 1 / (RRF_K + rank + 1)
        ranked = sorted(fused, key=lambda cid: (-fused[cid], -vector_scores.get(cid, 0)))[:k]
        passages = [Passage(**self.chunks[cid].model_dump(exclude={"test_only", "chunk_no"}),
                            vector_score=vector_scores.get(cid), fused_score=round(fused[cid], 5))
                    for cid in ranked]
        top = max(vector_scores.values(), default=0.0)
        return SearchResult(query=query, as_of=as_of, passages=passages, answerable=top >= self.embedder.min_score,
                            top_vector_score=top, min_score=self.embedder.min_score)

    async def search(self, query: str, *, as_of: date, countries: set[str] | None = None,
                     doc_types: set[str] | None = None, k: int = 6, include_test: bool = False) -> SearchResult:
        """The async entry point for the graph: embedding runs on the CPU, so it goes to a worker thread."""
        return await asyncio.to_thread(self.search_sync, query, as_of, countries, doc_types, k, include_test)


def all_chunks(include_test: bool = False) -> list[Chunk]:
    return [c for doc in corpus(include_test) for c in chunk_document(doc)]


@lru_cache(maxsize=2)
def retriever(include_test: bool = False) -> Retriever:
    """The app's retriever: the configured embedder and the on-disk index, synced with the corpus at first use."""
    return Retriever(all_chunks(include_test), make_embedder(), config.CHROMA_PATH, include_test)
