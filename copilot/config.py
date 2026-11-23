"""Settings from environment variables (see .env.example), read at import time."""
import os
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CORPUS_DIR = BASE_DIR / "corpus"
RULES_DIR = BASE_DIR / "rules"
SAMPLES_DIR = BASE_DIR / "samples" / "invoices"

# --- LLM (any OpenAI-compatible server; developed with LM Studio) ---
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:1235/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gemma-4-26b-a4b-it")
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "120"))
LLM_REASONING_EFFORT = os.environ.get("LLM_REASONING_EFFORT", "none")

# --- Knowledge base ---
EMBEDDER = os.environ.get("EMBEDDER", "onnx")              # onnx | fake
EMBED_MODEL = os.environ.get("EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EMBED_CACHE_DIR = Path(os.environ.get("EMBED_CACHE_DIR", BASE_DIR / "data" / "fastembed"))
CHROMA_PATH = Path(os.environ.get("CHROMA_PATH", BASE_DIR / "data" / "chroma"))
HYBRID_SEARCH = os.environ.get("HYBRID_SEARCH", "1") == "1"  # vector + BM25 (see evals/results/retrieval.md)

# --- Storage ---
APP_DB = Path(os.environ.get("APP_DB", BASE_DIR / "data" / "app.sqlite"))
CHECKPOINT_DB = Path(os.environ.get("CHECKPOINT_DB", BASE_DIR / "data" / "checkpoints.sqlite"))  # LangGraph threads
ATTACHMENTS_DIR = Path(os.environ.get("ATTACHMENTS_DIR", BASE_DIR / "data" / "attachments"))
HISTORY_TURNS = int(os.environ.get("HISTORY_TURNS", "6"))  # earlier messages the router sees

# --- Tickets: approved requirement drafts become ServiceNow records ---
SN_BACKEND = os.environ.get("SN_BACKEND", "fake")            # fake (SQLite in APP_DB) | rest (ServiceNow Table API)
SN_INSTANCE_URL = os.environ.get("SN_INSTANCE_URL", "")      # https://<instance>.service-now.com
SN_USER = os.environ.get("SN_USER", "")
SN_PASSWORD = os.environ.get("SN_PASSWORD", "")
SN_TABLE = os.environ.get("SN_TABLE", "u_localization_requirement")
SN_TIMEOUT_SECONDS = float(os.environ.get("SN_TIMEOUT_SECONDS", "15"))

# --- Corpus ---
# 1 = also load corpus/test-only (a poisoned document for injection evals). Never in the demo.
CORPUS_INCLUDE_TEST = os.environ.get("CORPUS_INCLUDE_TEST", "0") == "1"

# --- Validation ---
MAX_UPLOAD_KB = int(os.environ.get("MAX_UPLOAD_KB", "512"))

# "Today" for questions without a date. Empty = the real date.
FROZEN_TODAY = os.environ.get("FROZEN_TODAY", "")


def today() -> date:
    return date.fromisoformat(FROZEN_TODAY) if FROZEN_TODAY else date.today()
