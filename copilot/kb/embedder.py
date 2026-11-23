"""Text embeddings: ONNX models on the CPU (fastembed, no torch) and a deterministic fake for tests and CI.

The CPU keeps the GPU's memory free for the chat model. Each model has its own relevance threshold (`min_score`)
for the `answerable` rule, calibrated on this corpus with evals/retrieval_benchmark.py.
"""
import hashlib
import math
import re
from typing import Protocol

from copilot import config

# Cosine similarity the best passage needs for a question to count as answerable, per model. Calibrated on the
# benchmark's answerable vs unanswerable questions (evals/results/retrieval.md).
MODELS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": {"min_score": 0.40},
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": {"min_score": 0.40},
}


class Embedder(Protocol):
    name: str
    min_score: float

    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OnnxEmbedder:
    def __init__(self, model: str | None = None, cache_dir=None):
        self.name = model or config.EMBED_MODEL
        self.min_score = MODELS.get(self.name, {"min_score": 0.5})["min_score"]
        self._cache_dir = str(cache_dir or config.EMBED_CACHE_DIR)
        self._model = None

    def _load(self):
        if self._model is None:  # lazy: loading takes a few seconds and is not needed until the first search
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.name, cache_dir=self._cache_dir)
        return self._model

    def embed_passages(self, texts):
        return [v.tolist() for v in self._load().embed(texts)]

    def embed_query(self, text):
        return next(iter(self._load().embed([text]))).tolist()


WORD = re.compile(r"\w+", re.U)


class FakeEmbedder:
    """Hashed bag of words: texts that share words score high. Enough to test filters and wiring, not quality."""

    name = "fake-hashing-256"
    min_score = 0.3
    dims = 256

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        for word in WORD.findall(text.lower()):
            if len(word) > 2:
                vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dims] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    def embed_passages(self, texts):
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


def make_embedder(kind: str | None = None, model: str | None = None) -> Embedder:
    kind = kind or config.EMBEDDER
    if kind == "fake":
        return FakeEmbedder()
    if kind == "onnx":
        return OnnxEmbedder(model)
    raise ValueError(f"Unknown EMBEDDER '{kind}' (use onnx or fake)")
