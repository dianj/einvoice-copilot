"""FakeServiceNow: the same interface on a local SQLite table (the default backend; tests and the offline demo)."""
from datetime import datetime

import aiosqlite

from copilot import config
from copilot.integrations.servicenow.models import RequirementDraft, TicketDetail, TicketRef, TicketSummary

SCHEMA = """CREATE TABLE IF NOT EXISTS tickets (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT UNIQUE NOT NULL, sys_id TEXT NOT NULL,
    title TEXT NOT NULL, country TEXT NOT NULL, effective_date TEXT, user_story TEXT NOT NULL,
    acceptance_criteria TEXT NOT NULL, rule_ids TEXT NOT NULL, doc_refs TEXT NOT NULL, priority TEXT NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL, source_thread TEXT NOT NULL, created_at TEXT NOT NULL)"""
FIRST_NUMBER = 1001


class FakeServiceNow:
    def __init__(self, path=None):
        self.path = path or config.APP_DB

    async def _db(self) -> aiosqlite.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute(SCHEMA)
        return db

    async def create_requirement(self, draft: RequirementDraft, idempotency_key: str,
                                 source_thread: str) -> TicketRef:
        db = await self._db()
        try:
            async with db.execute("SELECT number, sys_id FROM tickets WHERE idempotency_key = ?",
                                  (idempotency_key,)) as cur:
                row = await cur.fetchone()
            if row:
                return TicketRef(number=row["number"], sys_id=row["sys_id"], created=False)
            async with db.execute("SELECT MAX(seq) FROM tickets") as cur:
                last = (await cur.fetchone())[0]
            seq = FIRST_NUMBER if last is None else last + 1
            number, sys_id = f"LOCREQ{seq:07d}", f"fake{seq:028d}"
            await db.execute(
                "INSERT INTO tickets (seq, number, sys_id, title, country, effective_date, user_story, "
                "acceptance_criteria, rule_ids, doc_refs, priority, idempotency_key, source_thread, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (seq, number, sys_id, draft.title, draft.country,
                 draft.effective_date.isoformat() if draft.effective_date else None, draft.user_story,
                 "\n".join(draft.acceptance_criteria), ",".join(draft.rule_ids), "; ".join(draft.doc_refs),
                 draft.priority, idempotency_key, source_thread, datetime.now().isoformat(sep=" ", timespec="seconds")))
            await db.commit()
            return TicketRef(number=number, sys_id=sys_id, created=True)
        finally:
            await db.close()

    async def get_ticket(self, number: str) -> TicketDetail | None:
        db = await self._db()
        try:
            async with db.execute("SELECT * FROM tickets WHERE number = ?", (number,)) as cur:
                row = await cur.fetchone()
        finally:
            await db.close()
        if row is None:
            return None
        return TicketDetail(
            number=row["number"], title=row["title"], country=row["country"], effective_date=row["effective_date"],
            priority=row["priority"], created_at=row["created_at"], user_story=row["user_story"],
            acceptance_criteria=row["acceptance_criteria"].split("\n"),
            rule_ids=[r for r in row["rule_ids"].split(",") if r], doc_refs=row["doc_refs"].split("; "),
            source_thread=row["source_thread"], idempotency_key=row["idempotency_key"])

    async def list_recent(self, limit: int = 20) -> list[TicketSummary]:
        db = await self._db()
        try:
            async with db.execute("SELECT * FROM tickets ORDER BY seq DESC LIMIT ?", (limit,)) as cur:
                rows = await cur.fetchall()
        finally:
            await db.close()
        return [TicketSummary(number=r["number"], title=r["title"], country=r["country"],
                              effective_date=r["effective_date"], priority=r["priority"],
                              created_at=r["created_at"]) for r in rows]
