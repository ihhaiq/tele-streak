from __future__ import annotations

import logging
import re
from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineQueryResultArticle,
    InputRichMessageContent,
    InputTextMessageContent,
    Message,
)

from app.database.repository import Repository
from app.services.rich_status import build_streak_fallback_text, build_streak_rich_message

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(r"(?:^|\s)streak:([A-Za-z0-9_-]{8,32})(?:\s|$)")


def extract_streak_guest_token(text: str | None) -> str | None:
    if not text:
        return None
    match = TOKEN_RE.search(text)
    return match.group(1) if match else None


def build_router(repository: Repository) -> Router:
    router = Router(name="guest_messages")

    @router.guest_message()
    async def on_guest_message(message: Message) -> None:
        token = extract_streak_guest_token(message.text)
        if token is None or message.guest_query_id is None:
            return

        request = await repository.get_guest_streak_request(token)
        if request is None:
            logger.warning(
                "STREAK_GUEST_REQUEST_INVALID chat=%s",
                message.chat.id,
            )
            return

        logger.info(
            "STREAK_GUEST_RECEIVED connection=%s chat=%s guest_chat=%s",
            request.business_connection_id,
            request.chat_id,
            message.chat.id,
        )
        streak = await repository.get_streak(
            request.business_connection_id,
            request.chat_id,
        )
        if streak is None:
            logger.warning(
                "STREAK_GUEST_RECORD_MISSING connection=%s chat=%s",
                request.business_connection_id,
                request.chat_id,
            )
            return
        timezone_name = await repository.get_connection_timezone(
            request.business_connection_id
        )

        rich_message = build_streak_rich_message(
            current=streak.current_streak,
            longest=streak.longest_streak,
            completed_days=streak.completed_days,
            break_count=streak.break_count,
            freeze_count=streak.freeze_count,
            last_completed_day=streak.last_completed_day,
            timezone_name=timezone_name,
        )
        result = InlineQueryResultArticle(
            id=f"streak-{token}",
            title="حالة الستريك",
            input_message_content=InputRichMessageContent(
                rich_message=rich_message,
            ),
        )
        try:
            await message.answer_guest_query(result)
        except TelegramBadRequest as error:
            logger.warning(
                "STREAK_GUEST_RICH_REJECTED connection=%s chat=%s error=%s",
                request.business_connection_id,
                request.chat_id,
                error,
            )
            fallback = InlineQueryResultArticle(
                id=f"streak-text-{token}",
                title="حالة الستريك",
                input_message_content=InputTextMessageContent(
                    message_text=build_streak_fallback_text(
                        current=streak.current_streak,
                        longest=streak.longest_streak,
                        completed_days=streak.completed_days,
                        break_count=streak.break_count,
                        freeze_count=streak.freeze_count,
                        last_completed_day=streak.last_completed_day,
                        timezone_name=timezone_name,
                    ),
                ),
            )
            await message.answer_guest_query(fallback)
            logger.info(
                "STREAK_GUEST_TEXT_SENT connection=%s chat=%s",
                request.business_connection_id,
                request.chat_id,
            )
        else:
            logger.info(
                "STREAK_GUEST_RICH_SENT connection=%s chat=%s guest_chat=%s",
                request.business_connection_id,
                request.chat_id,
                message.chat.id,
            )

        await repository.finish_guest_streak_request(token)

        if request.summon_message_id is not None:
            try:
                await message.bot.delete_business_messages(
                    business_connection_id=request.business_connection_id,
                    message_ids=[request.summon_message_id],
                )
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logger.info(
                    "STREAK_GUEST_SUMMON_DELETE_SKIPPED connection=%s chat=%s error=%s",
                    request.business_connection_id,
                    request.chat_id,
                    error,
                )
            else:
                logger.info(
                    "STREAK_GUEST_SUMMON_DELETED connection=%s chat=%s",
                    request.business_connection_id,
                    request.chat_id,
                )

    return router
