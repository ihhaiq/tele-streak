from __future__ import annotations

import asyncio
from collections import defaultdict
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
    duplicate: bool = False


@dataclass(slots=True)
class StreakStatus:
    current: int
    longest: int
    completed_days: int
    break_count: int
    freeze_count: int
    last_completed_day: str | None


class StreakService:
    def __init__(
        self,
        repository: Repository,
        timezone_name: str,
        poses: PoseCatalog,
    ):
        self.repository = repository
        self.tz = ZoneInfo(timezone_name)
        self.poses = poses
        self._locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(
            asyncio.Lock
        )

    def _days(self) -> tuple[str, str]:
        today_date = datetime.now(self.tz).date()
        yesterday = today_date - timedelta(days=1)
        return today_date.isoformat(), yesterday.isoformat()

    async def get_status(self, message: Message) -> StreakStatus | None:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return None
        if await self.repository.get_owner_id(connection_id) is None:
            return None

        record = await self.repository.get_streak(
            connection_id,
            message.chat.id,
        )
        if record is None:
            return StreakStatus(0, 0, 0, 0, 0, None)
        return StreakStatus(
            current=record.current_streak,
            longest=record.longest_streak,
            completed_days=record.completed_days,
            break_count=record.break_count,
            freeze_count=record.freeze_count,
            last_completed_day=record.last_completed_day,
        )

    async def register_message(self, message: Message) -> Completion:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return Completion(False)

        key = (connection_id, message.chat.id)
        async with self._locks[key]:
            owner_id = await self.repository.get_owner_id(connection_id)
            if owner_id is None:
                return Completion(False)

            sender_id = message.from_user.id
            role = "owner" if sender_id == owner_id else "peer"
            peer_id = None if role == "owner" else sender_id
            today, yesterday = self._days()

            result = await self.repository.register_activity(
                connection_id=connection_id,
                chat_id=message.chat.id,
                message_id=message.message_id,
                peer_user_id=peer_id,
                role=role,
                today=today,
                yesterday=yesterday,
                choose_pose=lambda days, last_pose: self.poses.choose(
                    days,
                    last_pose,
                ).id,
            )
            return Completion(
                completed=result.completed,
                days=result.days,
                pose=result.pose_id,
                duplicate=result.duplicate,
            )
