from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .engine import Database


@dataclass(slots=True)
class StreakRecord:
    business_connection_id: str
    chat_id: int
    peer_user_id: int | None
    current_streak: int
    longest_streak: int
    completed_days: int
    break_count: int
    last_completed_day: str | None
    owner_sent_day: str | None
    peer_sent_day: str | None
    last_pose: str | None
    last_success_message_id: int | None
    last_warning_day: str | None
    notifications_enabled: bool
    freeze_count: int
    freezes_used: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ActivityResult:
    completed: bool
    duplicate: bool
    days: int
    pose_id: str | None


class Repository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _streak_from_row(row) -> StreakRecord:
        return StreakRecord(
            business_connection_id=str(row["business_connection_id"]),
            chat_id=int(row["chat_id"]),
            peer_user_id=(
                int(row["peer_user_id"])
                if row["peer_user_id"] is not None
                else None
            ),
            current_streak=int(row["current_streak"]),
            longest_streak=int(row["longest_streak"]),
            completed_days=int(row["completed_days"]),
            break_count=int(row["break_count"]),
            last_completed_day=row["last_completed_day"],
            owner_sent_day=row["owner_sent_day"],
            peer_sent_day=row["peer_sent_day"],
            last_pose=row["last_pose"],
            last_success_message_id=(
                int(row["last_success_message_id"])
                if row["last_success_message_id"] is not None
                else None
            ),
            last_warning_day=row["last_warning_day"],
            notifications_enabled=bool(row["notifications_enabled"]),
            freeze_count=int(row["freeze_count"]),
            freezes_used=int(row["freezes_used"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

    async def upsert_connection(
        self,
        connection_id: str,
        owner_user_id: int,
        user_chat_id: int | None,
        is_enabled: bool,
        timezone_name: str = "Asia/Baghdad",
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                INSERT INTO business_connections(
                    business_connection_id, owner_user_id, user_chat_id,
                    is_enabled, timezone, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_connection_id) DO UPDATE SET
                    owner_user_id=excluded.owner_user_id,
                    user_chat_id=excluded.user_chat_id,
                    is_enabled=excluded.is_enabled,
                    updated_at=excluded.updated_at
                """,
                (
                    connection_id,
                    owner_user_id,
                    user_chat_id,
                    int(is_enabled),
                    timezone_name,
                    self._now(),
                ),
            )
            await db.commit()

    async def get_owner_id(self, connection_id: str) -> int | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT owner_user_id
                FROM business_connections
                WHERE business_connection_id=? AND is_enabled=1
                """,
                (connection_id,),
            )
            row = await cursor.fetchone()
            return int(row["owner_user_id"]) if row else None

    async def get_streak(
        self,
        connection_id: str,
        chat_id: int,
    ) -> StreakRecord | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            return self._streak_from_row(row) if row else None

    async def register_activity(
        self,
        *,
        connection_id: str,
        chat_id: int,
        message_id: int,
        peer_user_id: int | None,
        role: str,
        today: str,
        yesterday: str,
        choose_pose: Callable[[int, str | None], str],
    ) -> ActivityResult:
        if role not in {"owner", "peer"}:
            raise ValueError("role must be owner or peer")

        now = self._now()
        sender_column = (
            "owner_sent_day" if role == "owner" else "peer_sent_day"
        )
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            inserted = await db.execute(
                """
                INSERT OR IGNORE INTO processed_messages(
                    business_connection_id, chat_id, message_id, processed_at
                ) VALUES (?, ?, ?, ?)
                """,
                (connection_id, chat_id, message_id, now),
            )
            if inserted.rowcount == 0:
                await db.rollback()
                return ActivityResult(False, True, 0, None)

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
                    SET peer_user_id=COALESCE(peer_user_id, ?)
                    WHERE business_connection_id=? AND chat_id=?
                    """,
                    (peer_user_id, connection_id, chat_id),
                )

            await db.execute(
                f"""
                UPDATE streaks
                SET {sender_column}=?, updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (today, now, connection_id, chat_id),
            )
            cursor = await db.execute(
                """
                SELECT current_streak, longest_streak, completed_days,
                       break_count, last_completed_day, owner_sent_day,
                       peer_sent_day, last_pose
                FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            assert row is not None

            already_completed = row["last_completed_day"] == today
            both_sent = (
                row["owner_sent_day"] == today
                and row["peer_sent_day"] == today
            )
            if already_completed or not both_sent:
                await db.commit()
                return ActivityResult(
                    False,
                    False,
                    int(row["current_streak"]),
                    None,
                )

            consecutive = row["last_completed_day"] == yesterday
            new_streak = (
                int(row["current_streak"]) + 1 if consecutive else 1
            )
            was_broken = (
                row["last_completed_day"] is not None and not consecutive
            )
            break_count = int(row["break_count"]) + int(was_broken)
            completed_days = int(row["completed_days"]) + 1
            longest = max(int(row["longest_streak"]), new_streak)
            pose_id = choose_pose(new_streak, row["last_pose"])

            await db.execute(
                """
                UPDATE streaks SET
                    current_streak=?,
                    longest_streak=?,
                    completed_days=?,
                    break_count=?,
                    last_completed_day=?,
                    last_pose=?,
                    updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (
                    new_streak,
                    longest,
                    completed_days,
                    break_count,
                    today,
                    pose_id,
                    now,
                    connection_id,
                    chat_id,
                ),
            )
            await db.commit()
            return ActivityResult(True, False, new_streak, pose_id)

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

    async def get_sticker_file_id(self, sticker_key: str) -> str | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT telegram_file_id
                FROM sticker_cache
                WHERE sticker_key=?
                """,
                (sticker_key,),
            )
            row = await cursor.fetchone()
            return str(row["telegram_file_id"]) if row else None

    async def set_sticker_file_id(
        self,
        sticker_key: str,
        telegram_file_id: str,
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                INSERT INTO sticker_cache(sticker_key, telegram_file_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(sticker_key) DO UPDATE SET
                    telegram_file_id=excluded.telegram_file_id,
                    updated_at=excluded.updated_at
                """,
                (sticker_key, telegram_file_id, self._now()),
            )
            await db.commit()

    async def cleanup_processed_messages(self, keep_days: int = 7) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=keep_days)
        ).isoformat()
        async with self.database.connect() as db:
            cursor = await db.execute(
                "DELETE FROM processed_messages WHERE processed_at < ?",
                (cutoff,),
            )
            await db.commit()
            return cursor.rowcount

    async def stats(self) -> tuple[int, int]:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*) AS c
                FROM business_connections
                WHERE is_enabled=1
                """
            )
            connections = int((await cursor.fetchone())["c"])
            cursor = await db.execute("SELECT COUNT(*) AS c FROM streaks")
            streaks = int((await cursor.fetchone())["c"])
            return connections, streaks
