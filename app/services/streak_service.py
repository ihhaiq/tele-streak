from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import Message

from app.database.repository import Repository
from app.stickers.poses import PoseCatalog


@dataclass(slots=True)
class Completion:
    completed: bool
    days: int = 0
    pose: str | None = None


class StreakService:
    def __init__(self, repository: Repository, timezone_name: str, poses: PoseCatalog):
        self.repository = repository
        self.tz = ZoneInfo(timezone_name)
        self.poses = poses
        self._lock = asyncio.Lock()

    def _days(self) -> tuple[str, str]:
        today_date = datetime.now(self.tz).date()
        return today_date.isoformat(), (today_date - timedelta(days=1)).isoformat()

    async def register_message(self, message: Message) -> Completion:
        connection_id = message.business_connection_id
        if not connection_id:
            return Completion(False)

        async with self._lock:
            owner_id = await self.repository.get_owner_id(connection_id)
            if owner_id is None or message.from_user is None:
                return Completion(False)

            sender_id = message.from_user.id
            role = "owner" if sender_id == owner_id else "peer"
            peer_id = None if role == "owner" else sender_id
            record = await self.repository.get_or_create_streak(connection_id, message.chat.id, peer_id)
            today, yesterday = self._days()
            await self.repository.mark_sender_day(connection_id, message.chat.id, role, today)

            refreshed = await self.repository.get_streak(connection_id, message.chat.id)
            if not refreshed or refreshed.owner_sent_day != today or refreshed.peer_sent_day != today:
                return Completion(False)

            projected_days = record.current_streak + 1 if record.last_completed_day == yesterday else 1
            pose = self.poses.choose(projected_days, record.last_pose)
            completed, days = await self.repository.complete_day(
                connection_id, message.chat.id, today, yesterday, pose.id
            )
            return Completion(completed, days, pose.id if completed else None)
