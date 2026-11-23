"""Shared setup: environment before the app is imported (settings are read at import time)."""
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# No LLM in tests: point at a port nobody listens on, so the health check reports it as unreachable at once.
os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{_closed_port()}/v1"
os.environ["FROZEN_TODAY"] = "2026-05-15"
os.environ["CORPUS_INCLUDE_TEST"] = "0"
