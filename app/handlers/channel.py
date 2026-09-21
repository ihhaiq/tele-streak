from __future__ import annotations

from aiogram import Router
from aiogram.types import Message

from app.database.channel_repository import ChannelStreakRepository
from app.services.channel_streak_service import ChannelStreakService
from app.services.channel_permissions import channel_status_text


def build_router(repository: ChannelStreakRepository, streaks: ChannelStreakService) -> Router:
    router = Router(name="channel_streaks")

    @router.channel_post()
    async def on_channel_message(message: Message) -> None:
        text = (message.text or "").strip().lower()
        if text in {"بدأ ستريك", "بدا ستريك", "ابدأ ستريك", "start streak", "/startstreak"}:
            await repository.activate(message.chat.id)
            return
        if text in {"ستريك", "/ستريك", "streak", "/streak"}:
            streak = await repository.get(message.chat.id)
            await message.answer(channel_status_text(streak, streaks.timezone.key))
            return
        await streaks.register_post(message)

    return router
