from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import Message

from app.database.channel_repository import ChannelStreak, ChannelStreakRepository


class ChannelStreakService:
    def __init__(self, repository: ChannelStreakRepository, timezone_name: str, bot_user_id: int | None = None):
        self.repository = repository
        self.timezone = ZoneInfo(timezone_name)
        self.bot_user_id = bot_user_id
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def is_bot_post(message: Message) -> bool:
        sender = getattr(message, "sender_chat", None)
        return bool(getattr(sender, "type", None) == "bot") or bool(
            getattr(getattr(message, "from_user", None), "is_bot", False)
        )

    def is_own_bot_post(self, message: Message) -> bool:
        sender = getattr(message, "from_user", None)
        return bool(getattr(sender, "is_bot", False)) or (
            self.bot_user_id is not None and getattr(sender, "id", None) == self.bot_user_id
        )

    async def register_post(self, message: Message) -> tuple[ChannelStreak | None, bool]:
        if message.chat.type != "channel" or self.is_bot_post(message) or self.is_own_bot_post(message):
            return None, False
        lock = self._locks.setdefault(message.chat.id, asyncio.Lock())
        async with lock:
            streak = await self.repository.get(message.chat.id)
            if streak is None or not streak.is_enabled:
                return streak, False
            author = (getattr(message, "author_signature", None) or
                      getattr(getattr(message, "from_user", None), "full_name", None) or
                      "ناشر القناة")
            day = datetime.now(self.timezone).date().isoformat()
            return await self.repository.record_post(message.chat.id, day, author)
