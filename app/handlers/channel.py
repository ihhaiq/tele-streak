from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message

from app.database.channel_repository import ChannelStreakRepository
from app.services.channel_streak_service import ChannelStreakService
from app.services.channel_permissions import channel_status_text
from app.services.sticker_service import StickerService

logger = logging.getLogger(__name__)


def build_router(
    repository: ChannelStreakRepository,
    streaks: ChannelStreakService,
    stickers: StickerService,
) -> Router:
    router = Router(name="channel_streaks")

    @router.channel_post()
    async def on_channel_message(message: Message) -> None:
        text = (message.text or "").strip().lower()
        if text in {"بدأ ستريك", "بدا ستريك", "ابدأ ستريك", "start streak", "/startstreak"}:
            await repository.activate(message.chat.id)
            return
        if text in {"ستريك", "/ستريك", "streak", "/streak"}:
            streak = await repository.get(message.chat.id)
            if streak is not None and streak.is_enabled and streak.current_streak > 0:
                try:
                    await stickers.send_channel_success(
                        chat_id=message.chat.id,
                        days=streak.current_streak,
                    )
                except Exception:
                    logger.exception(
                        "CHANNEL_STREAK_STATUS_STICKER_FAILED chat=%s days=%s",
                        message.chat.id,
                        streak.current_streak,
                    )
            await message.answer(channel_status_text(streak, streaks.timezone.key))
            return
        streak, completed = await streaks.register_post(message)
        if not completed or streak is None:
            return

        try:
            await stickers.send_channel_success(
                chat_id=message.chat.id,
                days=streak.current_streak,
            )
        except Exception:
            logger.exception(
                "CHANNEL_STREAK_STICKER_FAILED chat=%s days=%s",
                message.chat.id,
                streak.current_streak,
            )

    return router
