from __future__ import annotations

from datetime import datetime
import logging
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InlineQueryResultCachedSticker,
    InputRichMessageContent,
    InputTextMessageContent,
    Message,
)

from app.database.revive_request_repository import ReviveApprovalState, ReviveRequestRepository
from app.database.repository import GuestStreakRequest, Repository
from app.keyboards.streak import streak_keyboard
from app.services.guest_delivery import GuestDeliveryService
from app.services.rich_status import build_streak_fallback_text, build_streak_rich_message
from app.services.sticker_service import StickerService
from app.services.streak_messages import BROKEN_NOTICE_TEXT, build_broken_notice_rich_message

logger = logging.getLogger(__name__)
TOKEN_RE = re.compile(
    r"(?:^|\s)streak:(status|success|warning_sticker|warning_notice|broken_notice|broken|revive):"
    r"([A-Za-z0-9_-]{8,32})(?:\s|$)"
)


def extract_streak_guest_request(text: str | None) -> tuple[str, str] | None:
    if not text:
        return None
    match = TOKEN_RE.search(text)
    if match is None:
        return None
    return match.group(1), match.group(2)


def _revive_text(state: ReviveApprovalState) -> str:
    owner = "✅" if state.owner_approved else "⏳"
    peer = "✅" if state.peer_approved else "⏳"
    return (
        "🧊 طلب إحياء الستريك\n\n"
        f"الطرف الأول: {owner}\n"
        f"الطرف الثاني: {peer}\n\n"
        "لا يتم إحياء الستريك إلا بعد موافقة الطرفين."
    )


def _revive_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ موافقة",
                    callback_data=f"streak_revive:approve:{token}",
                )
            ]
        ]
    )


async def _cleanup_summon(message: Message, request: GuestStreakRequest) -> None:
    if request.summon_message_id is None:
        return
    await message.bot.delete_business_messages(
        business_connection_id=request.business_connection_id,
        message_ids=[request.summon_message_id],
    )


async def _numbered_sticker_id(
    stickers: StickerService,
    repository: Repository,
    *,
    connection_id: str,
    days: int,
) -> str | None:
    key = f"streak:{days}"
    cached = await repository.get_sticker_file_id(key)
    if cached:
        return cached

    pack_id = stickers.pack.cached_file_id(str(days))
    if pack_id is None:
        try:
            pack_id = await stickers.pack.file_id(connection_id, days)
        except Exception:
            logger.exception(
                "STREAK_GUEST_STICKER_RESOLVE_FAILED connection=%s days=%s",
                connection_id,
                days,
            )
            return None
    if pack_id:
        await repository.set_sticker_file_id(key, pack_id)
    return pack_id


async def _special_sticker_id(
    stickers: StickerService,
    repository: Repository,
    *,
    connection_id: str,
    name: str,
) -> str | None:
    key = f"special:{name}"
    cached = await repository.get_sticker_file_id(key)
    if cached:
        return cached

    pack_id = stickers.pack.cached_file_id(name)
    if pack_id is None:
        try:
            pack_id = await stickers.pack.special_file_id(connection_id, name)
        except Exception:
            logger.exception(
                "STREAK_GUEST_SPECIAL_RESOLVE_FAILED connection=%s name=%s",
                connection_id,
                name,
            )
            return None
    if pack_id:
        await repository.set_sticker_file_id(key, pack_id)
    return pack_id


def _warning_text(streak, timezone_name: str | None) -> str:
    try:
        timezone = ZoneInfo(timezone_name or "Asia/Baghdad")
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Asia/Baghdad")
    today = datetime.now(timezone).date().isoformat()
    owner_missing = streak.owner_sent_day != today
    peer_missing = streak.peer_sent_day != today
    if owner_missing and peer_missing:
        missing = "أنتما لم ترسلا اليوم"
    elif owner_missing:
        missing = "صاحب الحساب لم يرسل اليوم"
    else:
        missing = "الطرف الثاني لم يرسل اليوم"
    return f"⏰ بقي أقل من ساعتين. {missing} وقد ينقطع الستريك."


def build_router(
    repository: Repository,
    stickers: StickerService,
    revive_requests: ReviveRequestRepository,
    guests: GuestDeliveryService,
) -> Router:
    router = Router(name="guest_messages")

    @router.guest_message()
    async def on_guest_message(message: Message) -> None:
        parsed = extract_streak_guest_request(message.text)
        if parsed is None or message.guest_query_id is None:
            return
        event, token = parsed

        request = await repository.get_guest_streak_request(token)
        if request is None:
            logger.warning("STREAK_GUEST_REQUEST_INVALID chat=%s event=%s", message.chat.id, event)
            return

        logger.info(
            "STREAK_GUEST_RECEIVED event=%s connection=%s chat=%s guest_chat=%s",
            event,
            request.business_connection_id,
            request.chat_id,
            message.chat.id,
        )

        streak = await repository.get_streak(
            request.business_connection_id,
            request.chat_id,
        )
        timezone_name = await repository.get_connection_timezone(
            request.business_connection_id
        )

        if event == "status":
            if streak is None:
                result = InlineQueryResultArticle(
                    id=f"streak-empty-{token}",
                    title="حالة الستريك",
                    input_message_content=InputTextMessageContent(
                        message_text="🔥 لا يوجد ستريك مفعّل في هذه المحادثة بعد."
                    ),
                )
            else:
                rich_message = build_streak_rich_message(
                    current=streak.current_streak,
                    longest=streak.longest_streak,
                    completed_days=streak.completed_days,
                    break_count=streak.break_count,
                    freeze_count=streak.freeze_count,
                    last_completed_day=streak.last_completed_day,
                    chat_id=streak.chat_id,
                    streak_mode=streak.streak_mode,
                    timezone_name=timezone_name,
                )
                result = InlineQueryResultArticle(
                    id=f"streak-{token}",
                    title="حالة الستريك",
                    input_message_content=InputRichMessageContent(
                        rich_message=rich_message,
                    ),
                )
        elif event == "success":
            if streak is None or streak.current_streak <= 0:
                result = InlineQueryResultArticle(
                    id=f"streak-success-empty-{token}",
                    title="الستريك",
                    input_message_content=InputTextMessageContent(
                        message_text="تعذر العثور على ملصق الستريك الحالي."
                    ),
                )
            else:
                file_id = await _numbered_sticker_id(
                    stickers,
                    repository,
                    connection_id=request.business_connection_id,
                    days=streak.current_streak,
                )
                result = (
                    InlineQueryResultCachedSticker(
                        id=f"streak-success-{token}",
                        sticker_file_id=file_id,
                        reply_markup=streak_keyboard(streak.current_streak),
                    )
                    if file_id
                    else InlineQueryResultArticle(
                        id=f"streak-success-text-{token}",
                        title="الستريك",
                        input_message_content=InputTextMessageContent(
                            message_text=f"🔥 الستريك: {streak.current_streak}"
                        ),
                    )
                )
        elif event == "warning_sticker":
            file_id = await _special_sticker_id(
                stickers,
                repository,
                connection_id=request.business_connection_id,
                name="warning",
            )
            result = (
                InlineQueryResultCachedSticker(
                    id=f"streak-warning-{token}",
                    sticker_file_id=file_id,
                )
                if file_id
                else InlineQueryResultArticle(
                    id=f"streak-warning-fallback-{token}",
                    title="تنبيه الستريك",
                    input_message_content=InputTextMessageContent(message_text="⏰ تنبيه الستريك"),
                )
            )
        elif event == "warning_notice":
            result = InlineQueryResultArticle(
                id=f"streak-warning-text-{token}",
                title="تنبيه الستريك",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        _warning_text(streak, timezone_name)
                        if streak is not None
                        else "⏰ قد ينقطع الستريك إذا لم يكتمل اليوم."
                    )
                ),
            )
        elif event == "broken_notice":
            result = InlineQueryResultArticle(
                id=f"streak-broken-notice-{token}",
                title="انقطع الستريك",
                input_message_content=InputRichMessageContent(
                    rich_message=build_broken_notice_rich_message(),
                ),
            )
        elif event == "broken":
            file_id = await _special_sticker_id(
                stickers,
                repository,
                connection_id=request.business_connection_id,
                name="broken",
            )
            result = (
                InlineQueryResultCachedSticker(
                    id=f"streak-broken-{token}",
                    sticker_file_id=file_id,
                )
                if file_id
                else InlineQueryResultArticle(
                    id=f"streak-broken-fallback-{token}",
                    title="انقطع الستريك",
                    input_message_content=InputTextMessageContent(
                        message_text="💔 انقطع الستريك. اكتب «احياء الستريك» لطلب إحيائه."
                    ),
                )
            )
        else:  # revive
            state = await revive_requests.create_or_get(
                request.business_connection_id,
                request.chat_id,
            )
            if state is None:
                result = InlineQueryResultArticle(
                    id=f"streak-revive-unavailable-{token}",
                    title="إحياء الستريك",
                    input_message_content=InputTextMessageContent(
                        message_text="لا يوجد ستريك مكسور قابل للإحياء حاليًا."
                    ),
                )
            else:
                result = InlineQueryResultArticle(
                    id=f"streak-revive-{token}",
                    title="طلب إحياء الستريك",
                    input_message_content=InputTextMessageContent(
                        message_text=_revive_text(state)
                    ),
                    reply_markup=_revive_keyboard(state.token),
                )

        try:
            await message.answer_guest_query(result)
        except TelegramBadRequest as error:
            if event == "broken_notice":
                logger.warning(
                    "STREAK_GUEST_BROKEN_RICH_REJECTED connection=%s chat=%s error=%s",
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
            elif event == "status" and streak is not None:
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
                            streak_mode=streak.streak_mode,
                            timezone_name=timezone_name,
                        ),
                    ),
                )
                await message.answer_guest_query(fallback)
            else:
                raise

        await repository.finish_guest_streak_request(token)
        if request.summon_message_id is not None:
            try:
                await _cleanup_summon(message, request)
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                logger.info(
                    "STREAK_GUEST_SUMMON_DELETE_SKIPPED event=%s connection=%s chat=%s error=%s",
                    event,
                    request.business_connection_id,
                    request.chat_id,
                    error,
                )
            else:
                logger.info(
                    "STREAK_GUEST_SENT event=%s connection=%s chat=%s",
                    event,
                    request.business_connection_id,
                    request.chat_id,
                )

        if event == "broken_notice":
            sticker_invoked = await guests.summon(
                event="broken",
                connection_id=request.business_connection_id,
                chat_id=request.chat_id,
                ttl_seconds=60,
            )
            if not sticker_invoked:
                logger.error(
                    "STREAK_GUEST_BROKEN_STICKER_INVOKE_FAILED connection=%s chat=%s",
                    request.business_connection_id,
                    request.chat_id,
                )

    return router
