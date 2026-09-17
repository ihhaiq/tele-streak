from __future__ import annotations

from contextlib import suppress
import re
import unicodedata

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from app.database.repository import GuestStreakRequest, Repository
from app.services.guest_delivery import GuestDeliveryService
from app.services.sticker_service import StickerService
from app.services.streak_test_service import StreakTestService, TestReviveState


TEST_GUEST_RE = re.compile(
    r"(?:^|\s)streak:test_revive:([A-Za-z0-9_-]{8,32})(?:\s|$)"
)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    return "".join(
        char for char in normalized
        if char != "ـ" and not unicodedata.combining(char)
    )


def parse_streak_test_query(text: str | None) -> str | None:
    normalized = _normalize(text)
    if normalized == "/streaktest":
        return "help"
    if normalized.startswith("/streaktest "):
        tail = normalized.split(maxsplit=1)[1]
    elif normalized == "اختبار ستريك":
        return "help"
    elif normalized.startswith("اختبار ستريك "):
        tail = normalized[len("اختبار ستريك "):].strip()
    else:
        return None

    aliases = {
        "مساعدة": "help",
        "help": "help",
        "حالة": "status",
        "status": "status",
        "نجاح": "success",
        "success": "success",
        "تحذير": "warning",
        "warning": "warning",
        "خسارة": "broken",
        "انكسار": "broken",
        "broken": "broken",
        "احياء": "revive",
        "revive": "revive",
        "الكل": "all",
        "all": "all",
    }
    return aliases.get(tail, "invalid")


def _test_revive_text(state: TestReviveState) -> str:
    owner = "✅" if state.owner_approved else "⏳"
    peer = "✅" if state.peer_approved else "⏳"
    return (
        "🧪 اختبار إحياء الستريك\n\n"
        f"الطرف الأول: {owner}\n"
        f"الطرف الثاني: {peer}\n\n"
        "لن يتغير الستريك الحقيقي ولن تُستهلك الحماية."
    )


def _test_revive_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ موافقة",
                    callback_data=f"streak_test:approve:{token}",
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


def build_router(
    repository: Repository,
    stickers: StickerService,
    guests: GuestDeliveryService,
    tests: StreakTestService,
) -> Router:
    router = Router(name="streak_test")

    @router.business_message(lambda message: parse_streak_test_query(message.text) is not None)
    async def on_streak_test(message: Message) -> None:
        action = parse_streak_test_query(message.text)
        connection_id = message.business_connection_id
        if action is None or not connection_id or message.from_user is None:
            return

        owner_user_id = await repository.get_owner_id(connection_id)
        if owner_user_id != message.from_user.id:
            return

        help_text = (
            "🧪 اختبار الستريك الآمن\n\n"
            "اكتب أحد الأوامر التالية في نفس محادثة الستريك:\n"
            "• اختبار ستريك نجاح\n"
            "• اختبار ستريك حالة\n"
            "• اختبار ستريك تحذير\n"
            "• اختبار ستريك خسارة\n"
            "• اختبار ستريك إحياء\n"
            "• اختبار ستريك الكل\n\n"
            "الاختبارات لا تغيّر عداد الستريك ولا تستهلك الحماية. "
            "اختبار الإحياء يحتاج أن تكون المحادثة مرتبطة بطرف ثانٍ أصلًا."
        )
        if action in {"help", "invalid"}:
            if action == "invalid":
                help_text = "❌ اختبار غير معروف.\n\n" + help_text
            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text=help_text,
            )
            return

        async def send_broken_preview() -> bool:
            return await guests.summon(
                event="broken_notice",
                connection_id=connection_id,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                ttl_seconds=120,
            )

        if action == "broken":
            if not await send_broken_preview():
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="❌ تعذر استدعاء Guest Mode لاختبار خسارة الستريك.",
                )
            return

        event_groups: dict[str, tuple[str, ...]] = {
            "status": ("status",),
            "success": ("success",),
            "warning": ("warning_sticker", "warning_notice"),
            "revive": ("test_revive",),
            "all": (
                "success",
                "status",
                "warning_sticker",
                "warning_notice",
            ),
        }
        failed: list[str] = []
        for event in event_groups[action]:
            sent = await guests.summon(
                event=event,
                connection_id=connection_id,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                ttl_seconds=120,
            )
            if not sent:
                failed.append(event)

        if action == "all":
            if not await send_broken_preview():
                failed.append("broken_notice")
            sent = await guests.summon(
                event="test_revive",
                connection_id=connection_id,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                ttl_seconds=120,
            )
            if not sent:
                failed.append("test_revive")

        if failed:
            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text=(
                    "❌ فشل استدعاء Guest Mode لبعض الاختبارات: "
                    + ", ".join(failed)
                ),
            )

    @router.guest_message(lambda message: bool(TEST_GUEST_RE.search(message.text or "")))
    async def on_test_revive_guest(message: Message) -> None:
        if message.guest_query_id is None:
            return
        match = TEST_GUEST_RE.search(message.text or "")
        if match is None:
            return
        guest_token = match.group(1)
        request = await repository.get_guest_streak_request(guest_token)
        if request is None:
            return

        state = await tests.create_revive_test(
            request.business_connection_id,
            request.chat_id,
        )
        if state is None:
            result = InlineQueryResultArticle(
                id=f"streak-test-revive-unavailable-{guest_token}",
                title="اختبار إحياء الستريك",
                input_message_content=InputTextMessageContent(
                    message_text=(
                        "🧪 تعذر بدء اختبار الإحياء. "
                        "فعّل الستريك في هذه المحادثة أولًا حتى يكون الطرفان معروفين."
                    )
                ),
            )
        else:
            result = InlineQueryResultArticle(
                id=f"streak-test-revive-{guest_token}",
                title="اختبار إحياء الستريك",
                input_message_content=InputTextMessageContent(
                    message_text=_test_revive_text(state)
                ),
                reply_markup=_test_revive_keyboard(state.token),
            )

        await message.answer_guest_query(result)
        await repository.finish_guest_streak_request(guest_token)
        if request.summon_message_id is not None:
            with suppress(TelegramBadRequest, TelegramForbiddenError):
                await _cleanup_summon(message, request)

    @router.callback_query(F.data.startswith("streak_test:approve:"))
    async def approve_test_revive(callback: CallbackQuery, bot: Bot) -> None:
        token = (callback.data or "").rsplit(":", 1)[-1]
        approval = await tests.approve(token, callback.from_user.id)

        if approval.status == "expired":
            await callback.answer(
                "انتهى اختبار الإحياء. اكتب «اختبار ستريك إحياء» من جديد.",
                show_alert=True,
            )
            return
        if approval.status == "unauthorized":
            await callback.answer(
                "فقط طرفا الستريك يستطيعان الموافقة حتى في الاختبار.",
                show_alert=True,
            )
            return
        if approval.status == "completed":
            await callback.answer("اكتمل هذا الاختبار مسبقًا.", show_alert=True)
            return

        state = approval.state
        if state is None:
            await callback.answer("تعذر قراءة حالة الاختبار.", show_alert=True)
            return

        if not approval.ready:
            if callback.inline_message_id:
                with suppress(TelegramBadRequest):
                    await bot.edit_message_text(
                        inline_message_id=callback.inline_message_id,
                        text=_test_revive_text(state),
                        reply_markup=_test_revive_keyboard(token),
                    )
            await callback.answer(
                "✅ تم تسجيل موافقتك. بانتظار الطرف الثاني."
                if approval.status == "approved"
                else "موافقتك مسجلة مسبقًا. بانتظار الطرف الثاني.",
                show_alert=True,
            )
            return

        final_text = (
            "✅ نجح اختبار الإحياء: وافق الطرفان بشكل مستقل.\n\n"
            "لم يتغير الستريك الحقيقي ولم تُستهلك أي حماية."
        )
        if callback.inline_message_id:
            with suppress(TelegramBadRequest):
                await bot.edit_message_text(
                    inline_message_id=callback.inline_message_id,
                    text=final_text,
                    reply_markup=None,
                )
        await callback.answer("✅ اختبار الإحياء نجح.", show_alert=True)

    return router
