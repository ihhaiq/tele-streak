from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import Message

from app.database.repository import Repository
from app.stickers.poses import PoseCatalog

logger = logging.getLogger(__name__)


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
    def __init__(self, repository: Repository, timezone_name: str, poses: PoseCatalog):
        self.repository = repository
        self.tz = ZoneInfo(timezone_name)
        self.poses = poses
        self._locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _days(self, connection_id: str) -> tuple[str, str]:
        timezone_name = await self.repository.get_connection_timezone(connection_id)
        timezone = ZoneInfo(timezone_name) if timezone_name else self.tz
        today_date = datetime.now(timezone).date()
        return today_date.isoformat(), (today_date - timedelta(days=1)).isoformat()

    async def _ensure_owner(self, message: Message) -> int | None:
        connection_id = message.business_connection_id
        if not connection_id:
            return None
        owner_id = await self.repository.get_owner_id(connection_id)
        if owner_id is not None:
            return owner_id
        try:
            connection = await message.bot.get_business_connection(connection_id)
            await self.repository.upsert_connection(
                connection_id=connection.id,
                owner_user_id=connection.user.id,
                user_chat_id=connection.user_chat_id,
                is_enabled=connection.is_enabled,
            )
            logger.info(
                "BUSINESS_CONNECTION_RECOVERED connection=%s owner=%s",
                connection.id,
                connection.user.id,
            )
            return connection.user.id if connection.is_enabled else None
        except Exception:
            logger.exception(
                "BUSINESS_CONNECTION_RECOVERY_FAILED connection=%s",
                connection_id,
            )
            return None

    async def get_status(self, message: Message) -> StreakStatus | None:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return None
        if await self._ensure_owner(message) is None:
            return None
        record = await self.repository.get_streak(connection_id, message.chat.id)
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
            owner_id = await self._ensure_owner(message)
            if owner_id is None:
                return Completion(False)
            sender_id = message.from_user.id
            role = "owner" if sender_id == owner_id else "peer"
            peer_id = None if role == "owner" else sender_id
            today, yesterday = await self._days(connection_id)
            result = await self.repository.register_activity(
                connection_id=connection_id,
                chat_id=message.chat.id,
                message_id=message.message_id,
                peer_user_id=peer_id,
                role=role,
                today=today,
                yesterday=yesterday,
                choose_pose=lambda days, last_pose: self.poses.choose(days, last_pose).id,
            )
            return Completion(
                completed=result.completed,
                days=result.days,
                pose=result.pose_id,
                duplicate=result.duplicate,
            )
