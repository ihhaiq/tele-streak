from __future__ import annotations

import logging
import unicodedata

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

from app.database.repository import Repository
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


def build_router(streaks: StreakService, stickers: StickerService, repository: Repository) -> Router:
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
            connection_id = message.business_connection_id
            if status is not None and connection_id:
                me = await message.bot.get_me()
                if me.username and bool(me.supports_guest_queries):
                    token = await repository.create_guest_streak_request(
                        connection_id,
                        message.chat.id,
                    )
                    if token is None:
                        logger.info(
                            "STREAK_GUEST_COOLDOWN connection=%s chat=%s",
                            connection_id,
                            message.chat.id,
                        )
                        return
                    try:
                        summon = await message.bot.send_message(
                            chat_id=message.chat.id,
                            business_connection_id=connection_id,
                            text=f"@{me.username} streak:{token}",
                            disable_notification=True,
                        )
                    except TelegramBadRequest as error:
                        await repository.finish_guest_streak_request(token)
                        logger.warning(
                            "STREAK_GUEST_INVOKE_REJECTED connection=%s chat=%s error=%s",
                            connection_id,
                            message.chat.id,
                            error,
                        )
                    else:
                        await repository.set_guest_streak_summon_message(
                            token,
                            summon.message_id,
                        )
                        logger.info(
                            "STREAK_GUEST_INVOKE_SENT connection=%s chat=%s message=%s",
                            connection_id,
                            message.chat.id,
                            summon.message_id,
                        )
                        return

                logger.warning(
                    "STREAK_GUEST_UNAVAILABLE connection=%s chat=%s supports_guest=%s",
                    connection_id,
                    message.chat.id,
                    bool(me.supports_guest_queries),
                )
                timezone_name = await repository.get_connection_timezone(connection_id)
                await stickers.send_status(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    current=status.current,
                    longest=status.longest,
                    completed_days=status.completed_days,
                    break_count=status.break_count,
                    freeze_count=status.freeze_count,
                    last_completed_day=status.last_completed_day,
                    timezone_name=timezone_name,
                )
            elif connection_id:
                logger.warning(
                    "STREAK_COMMAND_STATUS_UNAVAILABLE connection=%s chat=%s",
                    connection_id,
                    message.chat.id,
                )
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="تعذر قراءة الستريك مؤقتًا. تأكد أن اتصال الأعمال مفعّل ثم حاول مجددًا.",
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
                "STREAK_STICKER_SEND_FAILED connection=%s chat=%s days=%s",
                message.business_connection_id,
                message.chat.id,
                completion.days,
            )

    return router
