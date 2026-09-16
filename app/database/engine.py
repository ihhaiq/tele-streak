from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
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
    timezone TEXT NOT NULL DEFAULT 'Asia/Baghdad',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    peer_user_id INTEGER,
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    completed_days INTEGER NOT NULL DEFAULT 0,
    break_count INTEGER NOT NULL DEFAULT 0,
    last_completed_day TEXT,
    owner_sent_day TEXT,
    peer_sent_day TEXT,
    last_pose TEXT,
    last_success_message_id INTEGER,
    last_warning_day TEXT,
    last_broken_day TEXT,
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    freeze_count INTEGER NOT NULL DEFAULT 0,
    auto_freeze INTEGER NOT NULL DEFAULT 1,
    freezes_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processed_messages (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS sticker_cache (
    sticker_key TEXT PRIMARY KEY,
    telegram_file_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS freeze_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    protected_day TEXT NOT NULL,
    used_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_streaks_peer
ON streaks(peer_user_id);

CREATE INDEX IF NOT EXISTS idx_streaks_connection
ON streaks(business_connection_id);

CREATE INDEX IF NOT EXISTS idx_streaks_chat
ON streaks(chat_id);

CREATE INDEX IF NOT EXISTS idx_streaks_last_completed
ON streaks(last_completed_day);

CREATE INDEX IF NOT EXISTS idx_processed_messages_time
ON processed_messages(processed_at);
"""


PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    # Durable enough for WAL while skipping an fsync on every commit.
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA temp_store=MEMORY",
    # Negative value means KiB, so this is a 16 MB page cache.
    "PRAGMA cache_size=-16000",
    "PRAGMA mmap_size=134217728",
)


MIGRATIONS = (
    "ALTER TABLE business_connections ADD COLUMN timezone TEXT NOT NULL DEFAULT 'Asia/Baghdad'",
    "ALTER TABLE streaks ADD COLUMN completed_days INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE streaks ADD COLUMN break_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE streaks ADD COLUMN last_warning_day TEXT",
    "ALTER TABLE streaks ADD COLUMN last_broken_day TEXT",
    "ALTER TABLE streaks ADD COLUMN notifications_enabled INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE streaks ADD COLUMN is_enabled INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE streaks ADD COLUMN freeze_count INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE streaks ADD COLUMN auto_freeze INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE streaks ADD COLUMN freezes_used INTEGER NOT NULL DEFAULT 0",
)


class Database:
    """One long-lived SQLite connection, serialized with an asyncio lock.

    Opening a connection per query costs a thread handshake, a file open and a
    WAL header read every time. A single shared connection removes that cost;
    the lock keeps `BEGIN IMMEDIATE` transactions from interleaving.
    """

    def __init__(self, path: Path):
        self.path = path
        self._connection: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def _open(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self.path, isolation_level=None)
        connection.row_factory = aiosqlite.Row
        for pragma in PRAGMAS:
            await connection.execute(pragma)
        return connection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._lock:
            if self._connection is None:
                self._connection = await self._open()
            try:
                yield self._connection
            except BaseException:
                with suppress(Exception):
                    await self._connection.rollback()
                raise

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connect() as db:
            await db.executescript(SCHEMA)
            for statement in MIGRATIONS:
                try:
                    await db.execute(statement)
                except aiosqlite.OperationalError as error:
                    if "duplicate column name" not in str(error).lower():
                        raise
            await db.commit()
            await db.execute("PRAGMA optimize")

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                with suppress(Exception):
                    await self._connection.close()
                self._connection = None
