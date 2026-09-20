from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
)

from app.database.revive_request_repository import ReviveApprovalState, ReviveRequestRepository
from app.database.repository import Repository
from app.streak_modes import STREAK_MODE_LABELS, STREAK_MODES
from app.services.rich_status import (
    build_streak_rich_message,
    current_day,
    protection_text,
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


def _mode_menu(chat_id: int, current_mode: str) -> InputRichMessage:
    labels = STREAK_MODE_LABELS
    buttons = []
    for mode in STREAK_MODES:
        label = labels[mode]
        if mode == current_mode:
            buttons.append(
                f'<tg-button type="disabled" style="primary">✓ {label}</tg-button>'
            )
        else:
            buttons.append(
                '<tg-button type="callback_data" style="primary" '
                f'data="streak_mode:set:{mode}:{chat_id}">{label}</tg-button>'
            )

    return InputRichMessage(
        html=(
            "<h1>🔥 وضع الستريك</h1>"
            "<p>اختار شنو لازم يرسل كل طرف حتى تنحسب رسالة اليوم للستريك.</p>"
            '<tg-button-row align="center">'
            + "".join(buttons)
            + "</tg-button-row>"
            "<footer>"
            f"الوضع الحالي: <b>{labels.get(current_mode, labels['message'])}</b><br>"
            '<tg-button type="callback_data" style="link" '
            f'data="streak_mode:cancel:{chat_id}">رجوع</tg-button>'
            "</footer>"
        ),
        is_rtl=True,
    )


async def _edit_rich_callback(
    callback: CallbackQuery,
    bot: Bot,
    rich_message: InputRichMessage,
) -> bool:
    if callback.inline_message_id:
        await bot.edit_message_text(
            inline_message_id=callback.inline_message_id,
            rich_message=rich_message,
        )
        return True
    if isinstance(callback.message, Message):
        await callback.message.edit_text(rich_message=rich_message)
        return True
    return False


async def _restore_status(
    callback: CallbackQuery,
    bot: Bot,
    repository: Repository,
    streak,
) -> None:
    timezone_name = await repository.get_connection_timezone(
        streak.business_connection_id
    )
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
    await _edit_rich_callback(callback, bot, rich_message)


def build_router(
    repository: Repository,
    revive_requests: ReviveRequestRepository,
) -> Router:
    router = Router(name="guest_callbacks")

    @router.callback_query(F.data.startswith("streak_mode:open:"))
    async def open_streak_mode(callback: CallbackQuery, bot: Bot) -> None:
        try:
            chat_id = int((callback.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return

        streak = await repository.get_owner_streak(callback.from_user.id, chat_id)
        if streak is None:
            await callback.answer(
                "فقط صاحب الحساب يكدر يغير وضع الستريك.",
                show_alert=True,
            )
            return

        try:
            edited = await _edit_rich_callback(
                callback,
                bot,
                _mode_menu(chat_id, streak.streak_mode),
            )
        except TelegramBadRequest:
            edited = False

        await callback.answer(
            "" if edited else "تعذر فتح إعداد وضع الستريك حاليًا.",
            show_alert=not edited,
        )

    @router.callback_query(F.data.startswith("streak_mode:set:"))
    async def set_streak_mode(callback: CallbackQuery, bot: Bot) -> None:
        parts = (callback.data or "").split(":")
        if len(parts) != 4:
            await callback.answer()
            return
        _, _, mode, raw_chat_id = parts
        try:
            chat_id = int(raw_chat_id)
        except ValueError:
            await callback.answer()
            return
        if mode not in STREAK_MODE_LABELS:
            await callback.answer("وضع غير صالح.", show_alert=True)
            return

        current = await repository.get_owner_streak(callback.from_user.id, chat_id)
        if current is None:
            await callback.answer(
                "فقط صاحب الحساب يكدر يغير وضع الستريك.",
                show_alert=True,
            )
            return
        timezone_name = await repository.get_connection_timezone(
            current.business_connection_id
        )
        streak = await repository.set_streak_mode(
            callback.from_user.id,
            chat_id,
            mode,
            current_day(timezone_name),
        )
        if streak is None:
            await callback.answer(
                "فقط صاحب الحساب يكدر يغير وضع الستريك.",
                show_alert=True,
            )
            return

        with suppress(TelegramBadRequest):
            await _restore_status(callback, bot, repository, streak)
        await callback.answer(
            f"تم تغيير وضع الستريك إلى: {STREAK_MODE_LABELS[mode]}",
            show_alert=True,
        )

    @router.callback_query(F.data.startswith("streak_mode:cancel:"))
    async def cancel_streak_mode(callback: CallbackQuery, bot: Bot) -> None:
        try:
            chat_id = int((callback.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return

        streak = await repository.get_owner_streak(callback.from_user.id, chat_id)
        if streak is None:
            await callback.answer("تعذر فتح حالة الستريك.", show_alert=True)
            return

        with suppress(TelegramBadRequest):
            await _restore_status(callback, bot, repository, streak)
        await callback.answer()

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
