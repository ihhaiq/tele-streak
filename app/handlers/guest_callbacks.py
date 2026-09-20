from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
)

from app.database.revive_request_repository import ReviveApprovalState, ReviveRequestRepository
from app.database.repository import Repository
from app.services.rich_status import (
    build_streak_rich_message,
    protection_text,
    streak_mode_label,
)


def _approval_text(state: ReviveApprovalState) -> str:
    owner = "✅" if state.owner_approved else "⏳"
    peer = "✅" if state.peer_approved else "⏳"
    return (
        "🧊 طلب إحياء الستريك\n\n"
        f"الطرف الأول: {owner}\n"
        f"الطرف الثاني: {peer}\n\n"
        "لا يتم إحياء الستريك إلا بعد موافقة الطرفين."
    )


def _approval_keyboard(token: str) -> InlineKeyboardMarkup:
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


def _mode_keyboard(token: str, current: str) -> InlineKeyboardMarkup:
    def button(label: str, mode: str) -> InlineKeyboardButton:
        selected = "✅ " if current == mode else ""
        return InlineKeyboardButton(
            text=f"{selected}{label}",
            callback_data=f"streak_mode:set:{mode}:{token}",
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("💬 أي رسالة", "message")],
            [button("🖼 صورة / فيديو", "media")],
            [button("🎙 بصمة صوتية", "voice")],
            [
                InlineKeyboardButton(
                    text="↩️ رجوع",
                    callback_data=f"streak_mode:back:{token}",
                )
            ],
        ]
    )


def _mode_text(current: str) -> str:
    return (
        "🔥 وضع الستريك\n\n"
        "اختار شنو لازم يرسل الطرفين حتى ينحسب يوم الستريك.\n\n"
        f"الوضع الحالي: {streak_mode_label(current)}"
    )


async def _edit_callback(
    callback: CallbackQuery,
    bot: Bot,
    *,
    text: str | None = None,
    rich_message: InputRichMessage | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        if callback.inline_message_id:
            await bot.edit_message_text(
                inline_message_id=callback.inline_message_id,
                text=text,
                rich_message=rich_message,
                reply_markup=reply_markup,
            )
            return True

        message = callback.message
        if message is None or not hasattr(message, "chat"):
            return False

        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.message_id,
            business_connection_id=getattr(message, "business_connection_id", None),
            text=text,
            rich_message=rich_message,
            reply_markup=reply_markup,
        )
        return True
    except (TelegramBadRequest, TelegramForbiddenError):
        return False


async def _restore_status(
    callback: CallbackQuery,
    bot: Bot,
    repository: Repository,
    token: str,
) -> bool:
    settings = await repository.get_streak_settings(token)
    if settings is None:
        return False
    streak = await repository.get_streak(
        settings.business_connection_id,
        settings.chat_id,
    )
    if streak is None:
        return False
    timezone_name = await repository.get_connection_timezone(
        settings.business_connection_id
    )
    rich_message = build_streak_rich_message(
        current=streak.current_streak,
        longest=streak.longest_streak,
        completed_days=streak.completed_days,
        break_count=streak.break_count,
        freeze_count=streak.freeze_count,
        last_completed_day=streak.last_completed_day,
        timezone_name=timezone_name,
        streak_mode=streak.streak_mode,
        settings_token=token,
    )
    return await _edit_callback(
        callback,
        bot,
        rich_message=rich_message,
        reply_markup=None,
    )


def build_router(
    repository: Repository,
    revive_requests: ReviveRequestRepository,
) -> Router:
    router = Router(name="guest_callbacks")

    @router.callback_query(F.data.startswith("streak_mode:"))
    async def change_streak_mode(callback: CallbackQuery, bot: Bot) -> None:
        data = callback.data or ""
        parts = data.split(":")
        if len(parts) < 3:
            await callback.answer("طلب غير صالح.", show_alert=True)
            return

        action = parts[1]
        if action == "set":
            if len(parts) != 4:
                await callback.answer("طلب غير صالح.", show_alert=True)
                return
            mode = parts[2]
            token = parts[3]
        elif action in {"open", "back"}:
            if len(parts) != 3:
                await callback.answer("طلب غير صالح.", show_alert=True)
                return
            mode = None
            token = parts[2]
        else:
            await callback.answer("طلب غير صالح.", show_alert=True)
            return

        settings = await repository.get_streak_settings(token)
        if settings is None:
            await callback.answer(
                "هذا الزر قديم أو الستريك لم يعد متاحًا.",
                show_alert=True,
            )
            return
        if not settings.allows(callback.from_user.id):
            await callback.answer(
                "فقط طرفا هذا الستريك يكدرون يغيرون وضعه.",
                show_alert=True,
            )
            return

        if action == "open":
            edited = await _edit_callback(
                callback,
                bot,
                text=_mode_text(settings.mode),
                reply_markup=_mode_keyboard(token, settings.mode),
            )
            if edited:
                await callback.answer()
            else:
                await callback.answer(
                    "تعذر فتح إعدادات وضع الستريك.",
                    show_alert=True,
                )
            return

        if action == "back":
            restored = await _restore_status(callback, bot, repository, token)
            if restored:
                await callback.answer()
            else:
                await callback.answer(
                    "تعذر الرجوع إلى حالة الستريك.",
                    show_alert=True,
                )
            return

        if action != "set" or mode not in {"message", "media", "voice"}:
            await callback.answer("وضع غير صالح.", show_alert=True)
            return

        changed = await repository.set_streak_mode(token, mode)
        if not changed:
            await callback.answer(
                "تعذر تغيير وضع الستريك حاليًا.",
                show_alert=True,
            )
            return

        restored = await _restore_status(callback, bot, repository, token)
        if not restored:
            await callback.answer(
                f"تم تغيير الوضع إلى {streak_mode_label(mode)}، لكن تعذر تحديث الرسالة.",
                show_alert=True,
            )
            return
        await callback.answer(
            f"تم تغيير وضع الستريك إلى {streak_mode_label(mode)}."
        )

    @router.callback_query(F.data.startswith("streak_revive:approve:"))
    async def approve_revive(callback: CallbackQuery, bot: Bot) -> None:
        token = (callback.data or "").rsplit(":", 1)[-1]
        approval = await revive_requests.approve(token, callback.from_user.id)

        if approval.status == "expired":
            await callback.answer(
                "انتهت صلاحية طلب الإحياء. اكتب «احياء الستريك» من جديد.",
                show_alert=True,
            )
            return
        if approval.status == "unauthorized":
            await callback.answer(
                "فقط طرفا هذا الستريك يستطيعان الموافقة.",
                show_alert=True,
            )
            return
        if approval.status == "completed":
            await callback.answer("تم حسم هذا الطلب مسبقًا.", show_alert=True)
            return

        state = approval.state
        if state is None:
            await callback.answer("تعذر قراءة طلب الإحياء.", show_alert=True)
            return

        if not approval.ready:
            if callback.inline_message_id:
                with suppress(TelegramBadRequest):
                    await bot.edit_message_text(
                        inline_message_id=callback.inline_message_id,
                        text=_approval_text(state),
                        reply_markup=_approval_keyboard(token),
                    )
            await callback.answer(
                "تم تسجيل موافقتك. بانتظار موافقة الطرف الثاني."
                if approval.status == "approved"
                else "موافقتك مسجلة مسبقًا. بانتظار الطرف الثاني.",
                show_alert=True,
            )
            return

        result = await repository.revive_streak(
            state.business_connection_id,
            state.chat_id,
        )
        if result.status == "no_balance":
            final_text = "🧊 تعذر إحياء الستريك لأن رصيد الحماية نفد."
        elif result.status != "revived":
            final_text = "تعذر إحياء الستريك لأن حالته لم تعد قابلة للإحياء."
        else:
            final_text = (
                f"🔥 تم إحياء الستريك بموافقة الطرفين. عاد إلى {result.streak}.\n"
                f"الحماية المتبقية: {protection_text(result.freeze_count)}"
            )

        if callback.inline_message_id:
            with suppress(TelegramBadRequest):
                await bot.edit_message_text(
                    inline_message_id=callback.inline_message_id,
                    text=final_text,
                    reply_markup=None,
                )

        await callback.answer(final_text, show_alert=True)

    return router
