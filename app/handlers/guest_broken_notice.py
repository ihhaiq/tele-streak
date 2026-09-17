from __future__ import annotations

from contextlib import suppress
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
from app.services.broken_animation import BrokenAnimationService
from app.services.streak_messages import (
    BROKEN_NOTICE_TEXT,
    build_broken_notice_rich_message,
)

logger = logging.getLogger(__name__)

BROKEN_NOTICE_RE = re.compile(
    r"(?:^|\s)streak:broken_notice:([A-Za-z0-9_-]{8,32})(?:\s|$)"
)


def build_router(
    repository: Repository,
    broken_animation: BrokenAnimationService,
) -> Router:
    router = Router(name="guest_broken_notice")

    @router.guest_message(
        lambda message: bool(BROKEN_NOTICE_RE.search(message.text or ""))
    )
    async def on_broken_notice(message: Message) -> None:
        if message.guest_query_id is None:
            return
        match = BROKEN_NOTICE_RE.search(message.text or "")
        if match is None:
            return

        token = match.group(1)
        request = await repository.get_guest_streak_request(token)
        if request is None:
            return

        animation_file_id = await broken_animation.ensure_file_id(
            request.business_connection_id,
            request.chat_id,
        )
        result = InlineQueryResultArticle(
            id=f"streak-broken-notice-{token}",
            title="انقطع الستريك",
            input_message_content=InputRichMessageContent(
                rich_message=build_broken_notice_rich_message(animation_file_id),
            ),
        )
        try:
            await message.answer_guest_query(result)
        except TelegramBadRequest as error:
            logger.warning(
                "BROKEN_NOTICE_RICH_REJECTED connection=%s chat=%s error=%s",
                request.business_connection_id,
                request.chat_id,
                error,
            )
            fallback = InlineQueryResultArticle(
                id=f"streak-broken-notice-text-{token}",
                title="انقطع الستريك",
                input_message_content=InputTextMessageContent(
                    message_text=BROKEN_NOTICE_TEXT,
                ),
            )
            await message.answer_guest_query(fallback)

        await repository.finish_guest_streak_request(token)

        if request.summon_message_id is not None:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                await message.bot.delete_business_messages(
                    business_connection_id=request.business_connection_id,
                    message_ids=[request.summon_message_id],
                )

    return router
