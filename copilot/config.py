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

# --- Storage ---
APP_DB = Path(os.environ.get("APP_DB", BASE_DIR / "data" / "app.sqlite"))

# --- Corpus ---
# 1 = also load corpus/test-only (a poisoned document for injection evals). Never in the demo.
CORPUS_INCLUDE_TEST = os.environ.get("CORPUS_INCLUDE_TEST", "0") == "1"

# --- Validation ---
MAX_UPLOAD_KB = int(os.environ.get("MAX_UPLOAD_KB", "512"))

# "Today" for questions without a date. Empty = the real date.
FROZEN_TODAY = os.environ.get("FROZEN_TODAY", "")


def today() -> date:
    return date.fromisoformat(FROZEN_TODAY) if FROZEN_TODAY else date.today()
