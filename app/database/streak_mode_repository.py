from __future__ import annotations

from dataclasses import dataclass

from .engine import Database

STREAK_MODES = {"message", "media", "voice"}


@dataclass(frozen=True, slots=True)
class StreakModeTarget:
    business_connection_id: str
    chat_id: int


class StreakModeRepository:
    def __init__(self, database: Database):
        self.database = database

    async def get_mode(self, connection_id: str, chat_id: int) -> str:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT streak_mode FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            mode = str(row["streak_mode"]) if row else "message"
            return mode if mode in STREAK_MODES else "message"

    async def target_for_user(self, user_id: int, chat_id: int) -> StreakModeTarget | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT s.business_connection_id, s.chat_id
                FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE s.chat_id=?
                  AND b.is_enabled=1
                  AND (b.owner_user_id=? OR s.peer_user_id=?)
                ORDER BY b.updated_at DESC
                LIMIT 1
                """,
                (chat_id, user_id, user_id),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return StreakModeTarget(
                business_connection_id=str(row["business_connection_id"]),
                chat_id=int(row["chat_id"]),
            )

    async def set_mode(self, connection_id: str, chat_id: int, mode: str) -> bool:
        if mode not in STREAK_MODES:
            raise ValueError("unknown streak mode")
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                UPDATE streaks SET streak_mode=?, updated_at=datetime('now')
                WHERE business_connection_id=? AND chat_id=?
                """,
                (mode, connection_id, chat_id),
            )
            await db.commit()
            return cursor.rowcount == 1
