from __future__ import annotations

import logging
import re
from contextlib import suppress

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineQueryResultArticle,
    InputRichMessageContent,
    Message,
)

from app.database.repository import Repository
from app.services.rich_status import build_streak_rich_message

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

        request = await repository.consume_guest_streak_request(token)
        if request is None:
            logger.warning(
                "GUEST_STREAK_REQUEST_INVALID chat=%s",
                message.chat.id,
            )
            return

        streak = await repository.get_streak(
            request.business_connection_id,
            request.chat_id,
        )
        if streak is None:
            logger.warning(
                "GUEST_STREAK_RECORD_MISSING connection=%s chat=%s",
                request.business_connection_id,
                request.chat_id,
            )
            return

        rich_message = build_streak_rich_message(
            current=streak.current_streak,
            longest=streak.longest_streak,
            completed_days=streak.completed_days,
            break_count=streak.break_count,
            freeze_count=streak.freeze_count,
            last_completed_day=streak.last_completed_day,
        )
        result = InlineQueryResultArticle(
            id=f"streak-{token}",
            title="حالة الستريك",
            input_message_content=InputRichMessageContent(
                rich_message=rich_message,
            ),
        )
        await message.answer_guest_query(result)

        logger.info(
            "GUEST_STREAK_RICH_SENT connection=%s chat=%s guest_chat=%s",
            request.business_connection_id,
            request.chat_id,
            message.chat.id,
        )

        if request.summon_message_id is not None:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                await message.bot.delete_business_messages(
                    business_connection_id=request.business_connection_id,
                    message_ids=[request.summon_message_id],
                )

    return router
