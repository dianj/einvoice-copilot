"""Shared setup: environment before the app is imported (settings are read at import time), and a live server."""
import os
import socket
import sys
import tempfile
import threading
import time

import pytest

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
os.environ["EMBEDDER"] = "fake"                  # no model download in tests; the benchmark measures the real one
_DATA = tempfile.mkdtemp(prefix="einvoice-tests-")
os.environ["CHROMA_PATH"] = os.path.join(_DATA, "chroma")
os.environ["CHECKPOINT_DB"] = os.path.join(_DATA, "checkpoints.sqlite")
os.environ["ATTACHMENTS_DIR"] = os.path.join(_DATA, "attachments")


@pytest.fixture(scope="session")
def _fake_lm_server():
    from fake_lmstudio import FakeLMStudio

    fake = FakeLMStudio().start()
    yield fake
    fake.stop()


@pytest.fixture
def fake_lm(_fake_lm_server, monkeypatch):
    """The scripted model, empty at the start of each test; the app talks to it instead of LM Studio."""
    from copilot import config

    _fake_lm_server.reset()
    monkeypatch.setattr(config, "LLM_BASE_URL", _fake_lm_server.base_url)
    yield _fake_lm_server


@pytest.fixture(scope="session")
def app_url():
    """Run the real FastAPI app (uvicorn) in a background thread, for the browser tests."""
    import uvicorn

    from server import app

    port = _closed_port()
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not uv.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    uv.should_exit = True
    thread.join(timeout=5)


def pytest_collection_modifyitems(items):
    """Browser tests last: Playwright's sync API leaves an event loop running in the main thread, after which
    asyncio.run() in the async tests would fail."""
    items.sort(key=lambda item: item.get_closest_marker("e2e") is not None)
