from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import Message

from app.database.channel_repository import ChannelStreak, ChannelStreakRepository


class ChannelStreakService:
    def __init__(self, repository: ChannelStreakRepository, timezone_name: str):
        self.repository = repository
        self.timezone = ZoneInfo(timezone_name)
        self._locks: dict[int, asyncio.Lock] = {}

    @staticmethod
    def is_bot_post(message: Message) -> bool:
        sender = getattr(message, "sender_chat", None)
        return bool(getattr(sender, "type", None) == "bot") or bool(
            getattr(getattr(message, "from_user", None), "is_bot", False)
        )

    async def register_post(self, message: Message) -> tuple[ChannelStreak | None, bool]:
        if message.chat.type != "channel" or self.is_bot_post(message):
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
