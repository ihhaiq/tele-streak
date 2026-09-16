from __future__ import annotations

import logging
import unicodedata

from aiogram import Router
from aiogram.types import Message

from app.services.message_filter import should_count
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService

logger = logging.getLogger(__name__)


def is_streak_query(text: str | None) -> bool:
    if not text:
        return False
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    normalized = "".join(
        char for char in normalized
        if char != "ـ" and not unicodedata.combining(char)
    )
    first = normalized.split(maxsplit=1)[0] if normalized else ""
    first = first.split("@", 1)[0]
    return first in {"ستريك", "/ستريك", "streak", "/streak"}


def build_router(streaks: StreakService, stickers: StickerService) -> Router:
    router = Router(name="business_messages")

    @router.business_message()
    async def on_business_message(message: Message) -> None:
        if is_streak_query(message.text):
            logger.info(
                "STREAK_COMMAND connection=%s chat=%s message=%s",
                message.business_connection_id,
                message.chat.id,
                message.message_id,
            )
            status = await streaks.get_status(message)
            if status is not None and message.business_connection_id:
                await stickers.send_status(
                    connection_id=message.business_connection_id,
                    chat_id=message.chat.id,
                    current=status.current,
                    longest=status.longest,
                    completed_days=status.completed_days,
                    break_count=status.break_count,
                    freeze_count=status.freeze_count,
                    last_completed_day=status.last_completed_day,
                )
            elif message.business_connection_id:
                logger.warning(
                    "STREAK_COMMAND_STATUS_UNAVAILABLE connection=%s chat=%s",
                    message.business_connection_id,
                    message.chat.id,
                )
                await stickers.send_notice_text(
                    connection_id=message.business_connection_id,
                    chat_id=message.chat.id,
                    text="تعذر قراءة الستريك مؤقتًا. تأكد أن اتصال Business مفعّل ثم حاول مجددًا.",
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
            logger.exception(
                "Streak completed but sticker send failed: connection=%s chat=%s days=%s",
                message.business_connection_id,
                message.chat.id,
                completion.days,
            )

    return router
