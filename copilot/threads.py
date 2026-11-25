"""Who may use a conversation: thread ids are made by the server and bound to the browser that created them.

The browser gets a random session token in an httpOnly cookie; the app stores only its SHA-256 next to each thread id
(`threads` table in APP_DB). Reading a thread, sending a message to it and answering its approval card all need the
cookie that created it; any other id is unknown (404), so a guessed or leaked id is not enough. This is the demo's
stand-in for real sign-in: production would bind threads to an authenticated user and give approvers their own role.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime

import aiosqlite

from copilot import config

COOKIE = "einvoice_session"
SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
    thread_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,             -- SHA-256 of the session token, never the token itself
    created_at TEXT NOT NULL
);
"""


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _owner(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _db() -> aiosqlite.Connection:
    config.APP_DB.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(config.APP_DB)
    await db.executescript(SCHEMA)
    return db


async def create(token: str) -> str:
    """A new thread for this session."""
    thread_id = uuid.uuid4().hex
    db = await _db()
    try:
        await db.execute("INSERT INTO threads (thread_id, owner, created_at) VALUES (?, ?, ?)",
                         (thread_id, _owner(token), datetime.now(UTC).isoformat(timespec="seconds")))
        await db.commit()
    finally:
        await db.close()
    return thread_id


async def owned(thread_id: str, token: str | None) -> bool:
    """True only when the thread exists and this session created it."""
    if not token:
        return False
    db = await _db()
    try:
        async with db.execute("SELECT owner FROM threads WHERE thread_id = ?", (thread_id,)) as cur:
            row = await cur.fetchone()
    finally:
        await db.close()
    return row is not None and hmac.compare_digest(row[0], _owner(token))
