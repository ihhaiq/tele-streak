from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS business_connections (
    business_connection_id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    user_chat_id INTEGER,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    peer_user_id INTEGER,
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    last_completed_day TEXT,
    owner_sent_day TEXT,
    peer_sent_day TEXT,
    last_pose TEXT,
    last_success_message_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_streaks_peer
ON streaks(peer_user_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        # aiosqlite.Connection starts its worker thread when awaited / entered.
        # Keep that lifecycle in one place so the same connection is never
        # awaited and then entered a second time (Python 3.13 raises
        # ``RuntimeError: threads can only be started once`` in that case).
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=5000")
            yield db

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            await db.commit()
