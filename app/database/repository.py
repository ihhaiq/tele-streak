from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets

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
    last_broken_day: str | None
    notifications_enabled: bool
    is_enabled: bool
    freeze_count: int
    auto_freeze: bool
    freezes_used: int
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class ActivityResult:
    completed: bool
    duplicate: bool
    days: int
    pose_id: str | None


@dataclass(frozen=True, slots=True)
class ReviveResult:
    status: str
    streak: int = 0
    freeze_count: int = 0


@dataclass(frozen=True, slots=True)
class GuestStreakRequest:
    token: str
    business_connection_id: str
    chat_id: int
    summon_message_id: int | None


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
            last_broken_day=row["last_broken_day"],
            notifications_enabled=bool(row["notifications_enabled"]),
            is_enabled=bool(row["is_enabled"]),
            freeze_count=int(row["freeze_count"]),
            auto_freeze=bool(row["auto_freeze"]),
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

    async def create_guest_streak_request(
        self,
        connection_id: str,
        chat_id: int,
        *,
        ttl_seconds: int = 120,
    ) -> str:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()
        token = secrets.token_urlsafe(9)
        async with self.database.connect() as db:
            await db.execute(
                "DELETE FROM guest_streak_requests WHERE expires_at <= ? OR used_at IS NOT NULL",
                (now,),
            )
            await db.execute(
                """
                INSERT INTO guest_streak_requests(
                    token, business_connection_id, chat_id,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (token, connection_id, chat_id, now, expires_at),
            )
            await db.commit()
        return token

    async def set_guest_streak_summon_message(
        self,
        token: str,
        message_id: int,
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                UPDATE guest_streak_requests
                SET summon_message_id=?
                WHERE token=? AND used_at IS NULL
                """,
                (message_id, token),
            )
            await db.commit()

    async def consume_guest_streak_request(
        self,
        token: str,
    ) -> GuestStreakRequest | None:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT token, business_connection_id, chat_id, summon_message_id
                FROM guest_streak_requests
                WHERE token=? AND used_at IS NULL AND expires_at>?
                """,
                (token, now),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.rollback()
                return None
            await db.execute(
                "UPDATE guest_streak_requests SET used_at=? WHERE token=?",
                (now, token),
            )
            await db.commit()
            return GuestStreakRequest(
                token=str(row["token"]),
                business_connection_id=str(row["business_connection_id"]),
                chat_id=int(row["chat_id"]),
                summon_message_id=(
                    int(row["summon_message_id"])
                    if row["summon_message_id"] is not None
                    else None
                ),
            )

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
                    freeze_count, auto_freeze, freeze_seed_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, 3, 0, 1, ?, ?)
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
                       peer_sent_day, last_pose, is_enabled
                FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            assert row is not None
            if not bool(row["is_enabled"]):
                await db.commit()
                return ActivityResult(False, False, int(row["current_streak"]), None)

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
                row["last_completed_day"] is not None
                and not consecutive
                and int(row["current_streak"]) > 0
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
                    freeze_count=CASE
                        WHEN ? % 30 = 0 THEN MIN(freeze_count + 1, 3)
                        ELSE freeze_count
                    END,
                    last_completed_day=?,
                    last_pose=?,
                    revivable_streak=0,
                    revivable_day=NULL,
                    updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (
                    new_streak,
                    longest,
                    completed_days,
                    break_count,
                    completed_days,
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


    async def list_monitorable_streaks(
        self,
    ) -> list[tuple[StreakRecord, str]]:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT s.*, b.timezone
                FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE b.is_enabled=1
                  AND s.notifications_enabled=1
                  AND s.is_enabled=1
                  AND s.current_streak > 0
                """
            )
            rows = await cursor.fetchall()
            return [
                (self._streak_from_row(row), str(row["timezone"]))
                for row in rows
            ]

    async def claim_warning(
        self,
        connection_id: str,
        chat_id: int,
        day: str,
    ) -> bool:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                UPDATE streaks
                SET last_warning_day=?, updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                  AND COALESCE(last_warning_day, '') <> ?
                """,
                (day, self._now(), connection_id, chat_id, day),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def process_missed_day(
        self,
        *,
        connection_id: str,
        chat_id: int,
        today: str,
        missed_day: str,
        day_before_missed: str,
    ) -> str | None:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT current_streak, last_completed_day, last_broken_day,
                       freeze_count, freezes_used, auto_freeze
                FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            if (
                row is None
                or int(row["current_streak"]) <= 0
                or row["last_broken_day"] == today
                or row["last_completed_day"] == missed_day
            ):
                await db.rollback()
                return None

            can_freeze = (
                bool(row["auto_freeze"])
                and int(row["freeze_count"]) > 0
                and row["last_completed_day"] == day_before_missed
            )
            if can_freeze:
                await db.execute(
                    """
                    UPDATE streaks SET
                        freeze_count=freeze_count-1,
                        freezes_used=freezes_used+1,
                        last_completed_day=?,
                        revivable_streak=0,
                        revivable_day=NULL,
                        updated_at=?
                    WHERE business_connection_id=? AND chat_id=?
                    """,
                    (missed_day, now, connection_id, chat_id),
                )
                await db.execute(
                    """
                    INSERT INTO freeze_history(
                        business_connection_id, chat_id, protected_day, used_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (connection_id, chat_id, missed_day, now),
                )
                await db.commit()
                return "frozen"

            await db.execute(
                """
                UPDATE streaks SET
                    revivable_streak=current_streak,
                    revivable_day=?,
                    current_streak=0,
                    break_count=break_count+1,
                    last_broken_day=?,
                    updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (missed_day, today, now, connection_id, chat_id),
            )
            await db.commit()
            return "broken"

    async def revive_streak(
        self,
        connection_id: str,
        chat_id: int,
    ) -> ReviveResult:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT current_streak, freeze_count, break_count,
                       revivable_streak, revivable_day
                FROM streaks
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            row = await cursor.fetchone()
            if (
                row is None
                or int(row["current_streak"]) != 0
                or int(row["revivable_streak"]) <= 0
                or row["revivable_day"] is None
            ):
                await db.rollback()
                return ReviveResult("unavailable")

            freeze_count = int(row["freeze_count"])
            if freeze_count <= 0:
                await db.rollback()
                return ReviveResult("no_balance", freeze_count=0)

            restored_streak = int(row["revivable_streak"])
            protected_day = str(row["revivable_day"])
            remaining = freeze_count - 1
            await db.execute(
                """
                UPDATE streaks SET
                    current_streak=?,
                    freeze_count=?,
                    freezes_used=freezes_used+1,
                    break_count=CASE
                        WHEN break_count > 0 THEN break_count-1
                        ELSE 0
                    END,
                    last_completed_day=?,
                    last_broken_day=NULL,
                    revivable_streak=0,
                    revivable_day=NULL,
                    updated_at=?
                WHERE business_connection_id=? AND chat_id=?
                """,
                (
                    restored_streak,
                    remaining,
                    protected_day,
                    now,
                    connection_id,
                    chat_id,
                ),
            )
            await db.execute(
                """
                INSERT INTO freeze_history(
                    business_connection_id, chat_id, protected_day, used_at
                ) VALUES (?, ?, ?, ?)
                """,
                (connection_id, chat_id, protected_day, now),
            )
            await db.commit()
            return ReviveResult(
                "revived",
                streak=restored_streak,
                freeze_count=remaining,
            )

    async def get_connection_timezone(self, connection_id: str) -> str | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                "SELECT timezone FROM business_connections WHERE business_connection_id=? AND is_enabled=1",
                (connection_id,),
            )
            row = await cursor.fetchone()
            return str(row["timezone"]) if row else None

    async def set_owner_timezone(self, owner_user_id: int, timezone_name: str) -> int:
        async with self.database.connect() as db:
            cursor = await db.execute(
                "UPDATE business_connections SET timezone=?, updated_at=? WHERE owner_user_id=?",
                (timezone_name, self._now(), owner_user_id),
            )
            await db.commit()
            return cursor.rowcount

    async def dashboard_stats(self, owner_user_id: int) -> dict[str, int]:
        async with self.database.connect() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) AS c FROM business_connections WHERE owner_user_id=? AND is_enabled=1",
                (owner_user_id,),
            )
            connections = int((await cursor.fetchone())["c"])
            cursor = await db.execute(
                """
                SELECT COALESCE(SUM(s.is_enabled), 0) AS chats,
                       COALESCE(MAX(current_streak), 0) AS highest_current,
                       COALESCE(MAX(longest_streak), 0) AS highest_ever,
                       COALESCE(SUM(completed_days), 0) AS completed_days,
                       COALESCE(SUM(freezes_used), 0) AS freezes_used
                FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE b.owner_user_id=? AND b.is_enabled=1
                """,
                (owner_user_id,),
            )
            row = await cursor.fetchone()
            best_cursor = await db.execute(
                """
                SELECT s.chat_id FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE b.owner_user_id=? AND b.is_enabled=1
                ORDER BY s.longest_streak DESC, s.completed_days DESC LIMIT 1
                """,
                (owner_user_id,),
            )
            best = await best_cursor.fetchone()
            return {
                "connections": connections,
                "chats": int(row["chats"]),
                "highest_current": int(row["highest_current"]),
                "highest_ever": int(row["highest_ever"]),
                "completed_days": int(row["completed_days"]),
                "freezes_used": int(row["freezes_used"]),
                "best_chat_id": int(best["chat_id"]) if best else 0,
            }

    async def list_owner_streaks(self, owner_user_id: int) -> list[StreakRecord]:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT s.* FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE b.owner_user_id=? AND b.is_enabled=1
                ORDER BY s.current_streak DESC, s.updated_at DESC
                """,
                (owner_user_id,),
            )
            return [self._streak_from_row(row) for row in await cursor.fetchall()]

    async def get_owner_streak(self, owner_user_id: int, chat_id: int) -> StreakRecord | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT s.* FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE b.owner_user_id=? AND s.chat_id=? AND b.is_enabled=1
                LIMIT 1
                """,
                (owner_user_id, chat_id),
            )
            row = await cursor.fetchone()
            return self._streak_from_row(row) if row else None

    async def toggle_chat_setting(self, owner_user_id: int, chat_id: int, setting: str) -> bool | None:
        columns = {"enabled": "is_enabled", "notifications": "notifications_enabled", "auto_freeze": "auto_freeze"}
        column = columns.get(setting)
        if column is None:
            raise ValueError("unknown chat setting")
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                f"""
                UPDATE streaks SET {column}=1-{column}, updated_at=?
                WHERE chat_id=? AND business_connection_id IN (
                    SELECT business_connection_id FROM business_connections WHERE owner_user_id=?
                )
                """,
                (self._now(), chat_id, owner_user_id),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return None
            cursor = await db.execute(
                f"""
                SELECT {column} FROM streaks
                WHERE chat_id=? AND business_connection_id IN (
                    SELECT business_connection_id FROM business_connections WHERE owner_user_id=?
                ) LIMIT 1
                """,
                (chat_id, owner_user_id),
            )
            value = bool((await cursor.fetchone())[column])
            await db.commit()
            return value

    async def reset_streak(self, owner_user_id: int, chat_id: int) -> bool:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                UPDATE streaks SET current_streak=0, owner_sent_day=NULL,
                    peer_sent_day=NULL, last_completed_day=NULL,
                    last_pose=NULL, updated_at=?
                WHERE chat_id=? AND business_connection_id IN (
                    SELECT business_connection_id FROM business_connections WHERE owner_user_id=?
                )
                """,
                (self._now(), chat_id, owner_user_id),
            )
            await db.commit()
            return cursor.rowcount == 1

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
