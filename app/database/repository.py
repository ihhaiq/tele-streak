from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .engine import Database


@dataclass(slots=True)
class StreakRecord:
    business_connection_id: str
    chat_id: int
    peer_user_id: int | None
    current_streak: int
    longest_streak: int
    last_completed_day: str | None
    owner_sent_day: str | None
    peer_sent_day: str | None
    last_pose: str | None
    last_success_message_id: int | None
    created_at: str
    updated_at: str


class Repository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _streak_from_row(row) -> StreakRecord:
        # Map the DB schema explicitly. This prevents SELECT * from breaking the
        # dataclass if unrelated columns are added to the table later.
        return StreakRecord(
            business_connection_id=str(row["business_connection_id"]),
            chat_id=int(row["chat_id"]),
            peer_user_id=int(row["peer_user_id"]) if row["peer_user_id"] is not None else None,
            current_streak=int(row["current_streak"]),
            longest_streak=int(row["longest_streak"]),
            last_completed_day=row["last_completed_day"],
            owner_sent_day=row["owner_sent_day"],
            peer_sent_day=row["peer_sent_day"],
            last_pose=row["last_pose"],
            last_success_message_id=(
                int(row["last_success_message_id"])
                if row["last_success_message_id"] is not None
                else None
            ),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def upsert_connection(
        self,
        connection_id: str,
        owner_user_id: int,
        user_chat_id: int | None,
        is_enabled: bool,
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                INSERT INTO business_connections(
                    business_connection_id, owner_user_id, user_chat_id, is_enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(business_connection_id) DO UPDATE SET
                    owner_user_id=excluded.owner_user_id,
                    user_chat_id=excluded.user_chat_id,
                    is_enabled=excluded.is_enabled,
                    updated_at=excluded.updated_at
                """,
                (connection_id, owner_user_id, user_chat_id, int(is_enabled), self._now()),
            )
            await db.commit()

    async def get_owner_id(self, connection_id: str) -> int | None:
        async with self.database.connect() as db:
            cur = await db.execute(
                """
                SELECT owner_user_id
                FROM business_connections
                WHERE business_connection_id=? AND is_enabled=1
                """,
                (connection_id,),
            )
            row = await cur.fetchone()
            return int(row["owner_user_id"]) if row else None

    async def get_or_create_streak(
        self,
        connection_id: str,
        chat_id: int,
        peer_user_id: int | None,
    ) -> StreakRecord:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO streaks(
                    business_connection_id, chat_id, peer_user_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (connection_id, chat_id, peer_user_id, now, now),
            )
            if peer_user_id is not None:
                await db.execute(
                    """
                    UPDATE streaks
                    SET peer_user_id=COALESCE(peer_user_id, ?), updated_at=?
                    WHERE business_connection_id=? AND chat_id=?
                    """,
                    (peer_user_id, now, connection_id, chat_id),
                )
            await db.commit()
            cur = await db.execute(
                """
                SELECT * FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cur.fetchone()
            assert row is not None
            return self._streak_from_row(row)

    async def mark_sender_day(
        self,
        connection_id: str,
        chat_id: int,
        role: str,
        day: str,
    ) -> None:
        if role not in {"owner", "peer"}:
            raise ValueError("role must be owner or peer")
        column = "owner_sent_day" if role == "owner" else "peer_sent_day"
        async with self.database.connect() as db:
            await db.execute(
                f"""
                UPDATE streaks
                SET {column}=?, updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (day, self._now(), connection_id, chat_id),
            )
            await db.commit()

    async def get_streak(self, connection_id: str, chat_id: int) -> StreakRecord | None:
        async with self.database.connect() as db:
            cur = await db.execute(
                """
                SELECT * FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cur.fetchone()
            return self._streak_from_row(row) if row else None

    async def complete_day(
        self,
        connection_id: str,
        chat_id: int,
        today: str,
        yesterday: str,
        pose: str,
    ) -> tuple[bool, int]:
        """Atomically complete today. Returns (completed_now, current_streak)."""
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT current_streak, longest_streak, last_completed_day,
                       owner_sent_day, peer_sent_day
                FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cur.fetchone()
            if not row:
                await db.rollback()
                return False, 0

            if row["last_completed_day"] == today:
                await db.rollback()
                return False, int(row["current_streak"])

            if row["owner_sent_day"] != today or row["peer_sent_day"] != today:
                await db.rollback()
                return False, int(row["current_streak"])

            new_streak = int(row["current_streak"]) + 1 if row["last_completed_day"] == yesterday else 1
            longest = max(int(row["longest_streak"]), new_streak)
            await db.execute(
                """
                UPDATE streaks SET
                    current_streak=?,
                    longest_streak=?,
                    last_completed_day=?,
                    last_pose=?,
                    updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (new_streak, longest, today, pose, self._now(), connection_id, chat_id),
            )
            await db.commit()
            return True, new_streak

    async def set_success_message_id(
        self,
        connection_id: str,
        chat_id: int,
        message_id: int,
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                UPDATE streaks
                SET last_success_message_id=?, updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (message_id, self._now(), connection_id, chat_id),
            )
            await db.commit()

    async def stats(self) -> tuple[int, int]:
        async with self.database.connect() as db:
            cur = await db.execute("SELECT COUNT(*) AS c FROM business_connections WHERE is_enabled=1")
            connections = int((await cur.fetchone())["c"])
            cur = await db.execute("SELECT COUNT(*) AS c FROM streaks")
            streaks = int((await cur.fetchone())["c"])
            return connections, streaks
