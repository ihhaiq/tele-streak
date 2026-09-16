from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message

from app.services.message_filter import should_count
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService

logger = logging.getLogger(__name__)


def build_router(streaks: StreakService, stickers: StickerService) -> Router:
    router = Router(name="business_messages")

    @router.business_message()
    async def on_business_message(message: Message) -> None:
        if message.text and message.text.strip() == "ستريك":
            status = await streaks.get_status(message)
            if status is not None and message.business_connection_id:
                await stickers.send_status(
                    connection_id=message.business_connection_id,
                    chat_id=message.chat.id,
                    current=status.current,
                    longest=status.longest,
                    last_completed_day=status.last_completed_day,
                )
            return

        if not should_count(message):
            return

        completion = await streaks.register_message(message)
        if not completion.completed or completion.pose is None:
            return

        try:
            await stickers.send_success(
                connection_id=message.business_connection_id,
                chat_id=message.chat.id,
                pose=completion.pose,
                days=completion.days,
            )
        except Exception:
            # The streak is already safely committed; do not increment twice if Telegram send fails.
            logger.exception(
                "Streak completed but sticker send failed: connection=%s chat=%s days=%s",
                message.business_connection_id,
                message.chat.id,
                completion.days,
            )

    return router
