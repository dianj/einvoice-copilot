"""The vector index (Chroma, on disk). One collection per embedding model, so switching models never mixes vectors.

`sync` re-embeds only chunks whose content changed and deletes chunks that no longer exist, so a restart after
editing one document takes a moment, not a full rebuild.
"""
import logging
import re

import chromadb
from chromadb.config import Settings

from copilot.kb.chunker import Chunk

log = logging.getLogger("copilot.kb")


def collection_name(embedder_name: str, include_test: bool) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", embedder_name).strip("-").lower()[:50]
    return f"kb-{slug}{'-test' if include_test else ''}"


class VectorIndex:
    def __init__(self, path, embedder, include_test: bool = False, reset: bool = False):
        """`path=None` keeps the index in memory and always starts it empty (tests, benchmark); `reset` empties an
        index on disk (through Chroma, not by deleting files, which Windows locks while a client is open)."""
        self.embedder = embedder
        settings = Settings(anonymized_telemetry=False)
        name = collection_name(embedder.name, include_test)
        if path is None:
            client, reset = chromadb.EphemeralClient(settings=settings), True
        else:
            client = chromadb.PersistentClient(path=str(path), settings=settings)
        if reset and name in [c.name for c in client.list_collections()]:
            client.delete_collection(name)
        self.collection = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"},
                                                          embedding_function=None)

    def sync(self, chunks: list[Chunk]) -> dict:
        """Bring the index in line with the chunks. Returns counts of changed, removed and unchanged chunks."""
        by_id = {c.chunk_id: c for c in chunks}
        existing = self.collection.get(include=["metadatas"])
        stored = {cid: meta.get("hash") for cid, meta in zip(existing["ids"], existing["metadatas"], strict=True)}
        changed = [c for cid, c in by_id.items() if stored.get(cid) != c.content_hash]
        removed = [cid for cid in stored if cid not in by_id]
        if removed:
            self.collection.delete(ids=removed)
        if changed:
            self.collection.upsert(ids=[c.chunk_id for c in changed],
                                   embeddings=self.embedder.embed_passages([c.embed_text for c in changed]),
                                   documents=[c.text for c in changed], metadatas=[c.metadata() for c in changed])
        counts = {"changed": len(changed), "removed": len(removed), "unchanged": len(by_id) - len(changed)}
        if changed or removed:
            log.info("KB index %s synced: %s", self.collection.name, counts)
        return counts

    def query(self, text: str, where: dict, k: int) -> list[tuple[str, float]]:
        """(chunk_id, cosine similarity) of the nearest chunks that match the Chroma `where` filter."""
        k = min(k, self.collection.count())
        if k == 0:
            return []
        result = self.collection.query(query_embeddings=[self.embedder.embed_query(text)], n_results=k,
                                       where=where, include=["distances"])
        return [(cid, round(1 - distance, 4)) for cid, distance in zip(result["ids"][0], result["distances"][0],
                                                                       strict=True)]
