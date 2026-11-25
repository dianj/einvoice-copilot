# --- Stage 1: the embedding model ---------------------------------------------------------------------------------
# Downloaded at build time, so the container starts offline. A stage of its own that does not depend on
# requirements.txt: a dependency change does not download the 240 MB model again, and CI caches this layer.
FROM python:3.12-slim AS model
ENV PIP_NO_CACHE_DIR=1
RUN pip install "fastembed>=0.9.1,<1"
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', cache_dir='/models')"

# --- Stage 2: the app ---------------------------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# Exact versions from the lock, every file checked against its hash (SECURITY.md).
COPY requirements.lock .
RUN pip install --require-hashes -r requirements.lock

# Run as an unprivileged user; data/ is the only writable place. data/ is a volume, so the model lives outside it.
RUN useradd --create-home --uid 1000 app
ENV EMBED_CACHE_DIR=/app/models
COPY --from=model --chown=app:app /models /app/models
COPY --chown=app:app . .
RUN mkdir -p /app/data && chown app:app /app/data
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
