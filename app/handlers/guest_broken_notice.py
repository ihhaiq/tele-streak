from __future__ import annotations

from contextlib import suppress
import re

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineQueryResultArticle, InputTextMessageContent, Message

from app.database.repository import Repository


BROKEN_NOTICE_RE = re.compile(
    r"(?:^|\s)streak:broken_notice:([A-Za-z0-9_-]{8,32})(?:\s|$)"
)

BROKEN_NOTICE_TEXT = (
    "💔 الستريك مات.\n\n"
    "ما كملتوا شرط اليوم، ولهذا انقطع الستريك.\n\n"
    "إذا تريدون ترجعوه، واحد منكم يكتب «احياء الستريك» هنا. "
    "راح يطلع طلب إحياء، وبعدها لازم الطرفين يضغطون ✅ موافقة.\n\n"
    "إذا وافق طرف واحد بس، ما يرجع الستريك. وإذا وافقتوا اثنينكم، "
    "يستخدم البوت 🧊 من رصيد الحماية ويرجع الستريك مثل ما كان."
)


def build_router(repository: Repository) -> Router:
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

        result = InlineQueryResultArticle(
            id=f"streak-broken-notice-{token}",
            title="انقطع الستريك",
            input_message_content=InputTextMessageContent(
                message_text=BROKEN_NOTICE_TEXT,
            ),
        )
        await message.answer_guest_query(result)
        await repository.finish_guest_streak_request(token)

        if request.summon_message_id is not None:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                await message.bot.delete_business_messages(
                    business_connection_id=request.business_connection_id,
                    message_ids=[request.summon_message_id],
                )

    return router
