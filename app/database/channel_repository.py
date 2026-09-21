from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .engine import Database


@dataclass(frozen=True, slots=True)
class ChannelStreak:
    channel_id: int
    current_streak: int
    longest_streak: int
    completed_days: int
    break_count: int
    last_completed_day: str | None
    last_completed_by: str | None
    is_enabled: bool
    last_completed_by_user_id: int | None = None


class ChannelStreakRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _record(row) -> ChannelStreak | None:
        if row is None:
            return None
        return ChannelStreak(
            channel_id=int(row["channel_id"]), current_streak=int(row["current_streak"]),
            longest_streak=int(row["longest_streak"]), completed_days=int(row["completed_days"]),
            break_count=int(row["break_count"]), last_completed_day=row["last_completed_day"],
            last_completed_by=row["last_completed_by"], is_enabled=bool(row["is_enabled"]),
            last_completed_by_user_id=row["last_completed_by_user_id"],
        )

    async def get(self, channel_id: int) -> ChannelStreak | None:
        async with self.database.connect() as db:
            row = await (await db.execute(
                "SELECT * FROM channel_streaks WHERE channel_id=?", (channel_id,)
            )).fetchone()
            return self._record(row)

    async def activate(self, channel_id: int) -> ChannelStreak:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute("""INSERT INTO channel_streaks(channel_id, created_at, updated_at)
                VALUES (?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET is_enabled=1, updated_at=?""",
                (channel_id, now, now, now))
            await db.commit()
        record = await self.get(channel_id)
        assert record is not None
        return record

    async def set_enabled(self, channel_id: int, enabled: bool) -> None:
        async with self.database.connect() as db:
            await db.execute(
                "UPDATE channel_streaks SET is_enabled=?, updated_at=? WHERE channel_id=?",
                (int(enabled), self._now(), channel_id),
            )
            await db.commit()

    async def record_post(
        self, channel_id: int, day: str, author: str, author_user_id: int | None = None,
    ) -> tuple[ChannelStreak | None, bool]:
        now = self._now()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (await db.execute(
                "SELECT * FROM channel_streaks WHERE channel_id=?", (channel_id,)
            )).fetchone()
            if row is None or not row["is_enabled"] or row["last_completed_day"] == day:
                await db.rollback()
                # نبني النتيجة من الصف نفسه بدون دخول قفل الاتصال مرة ثانية.
                return self._record(row), False
            previous = row["last_completed_day"]
            current = int(row["current_streak"])
            yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            broken = bool(previous and previous != yesterday)
            current = 1 if broken else current + 1
            await db.execute(
                """UPDATE channel_streaks SET current_streak=?, longest_streak=MAX(longest_streak,?),
                completed_days=completed_days+1, break_count=?, last_completed_day=?, last_completed_by=?,
                last_completed_by_user_id=?, updated_at=? WHERE channel_id=?""",
                (current, current, int(row["break_count"]) + int(broken), day, author,
                 author_user_id, now, channel_id),
            )
            row = await (await db.execute(
                "SELECT * FROM channel_streaks WHERE channel_id=?", (channel_id,)
            )).fetchone()
            await db.commit()
            return self._record(row), True
