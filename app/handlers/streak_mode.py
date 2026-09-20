from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InputRichMessage, Message

from app.database.repository import Repository, StreakRecord
from app.services.rich_status import (
    build_streak_rich_message,
    current_day,
)
from app.streak_modes import (
    MODE_MESSAGE,
    STREAK_MODE_LABELS,
    STREAK_MODES,
    streak_mode_label,
)


def build_mode_menu(chat_id: int, current_mode: str) -> InputRichMessage:
    buttons: list[str] = []
    for mode in STREAK_MODES:
        label = STREAK_MODE_LABELS.get(mode, STREAK_MODE_LABELS[MODE_MESSAGE])
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
            "<p>اختار شنو لازم يرسل كل طرف حتى تنحسب مشاركته اليوم.</p>"
            '<tg-button-row align="center">'
            + "".join(buttons)
            + "</tg-button-row>"
            "<footer>"
            f"الوضع الحالي: <b>{streak_mode_label(current_mode)}</b><br>"
            '<tg-button type="callback_data" style="link" '
            f'data="streak_mode:cancel:{chat_id}">رجوع</tg-button>'
            "</footer>"
        ),
        is_rtl=True,
    )


async def _edit_rich(
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


async def _owner_streak(
    repository: Repository,
    callback: CallbackQuery,
    chat_id: int,
) -> StreakRecord | None:
    return await repository.get_owner_streak(callback.from_user.id, chat_id)


async def _restore_status(
    callback: CallbackQuery,
    bot: Bot,
    repository: Repository,
    streak,
) -> None:
    timezone_name = await repository.get_connection_timezone(
        streak.business_connection_id
    )
    await _edit_rich(
        callback,
        bot,
        build_streak_rich_message(
            current=streak.current_streak,
            longest=streak.longest_streak,
            completed_days=streak.completed_days,
            break_count=streak.break_count,
            freeze_count=streak.freeze_count,
            last_completed_day=streak.last_completed_day,
            chat_id=streak.chat_id,
            streak_mode=streak.streak_mode,
            timezone_name=timezone_name,
        ),
    )


def build_router(repository: Repository) -> Router:
    router = Router(name="streak_mode")

    @router.callback_query(F.data.startswith("streak_mode:open:"))
    async def open_mode(callback: CallbackQuery, bot: Bot) -> None:
        try:
            chat_id = int((callback.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return

        streak = await _owner_streak(repository, callback, chat_id)
        if streak is None:
            await callback.answer(
                "فقط صاحب الحساب يكدر يغير وضع الستريك.",
                show_alert=True,
            )
            return

        try:
            edited = await _edit_rich(
                callback,
                bot,
                build_mode_menu(chat_id, streak.streak_mode),
            )
        except TelegramBadRequest:
            edited = False

        await callback.answer(
            "" if edited else "تعذر فتح إعداد وضع الستريك حاليًا.",
            show_alert=not edited,
        )

    @router.callback_query(F.data.startswith("streak_mode:set:"))
    async def set_mode(callback: CallbackQuery, bot: Bot) -> None:
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

        current = await _owner_streak(repository, callback, chat_id)
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
            current.business_connection_id,
            chat_id,
            mode,
            current_day(timezone_name),
        )
        if streak is None:
            await callback.answer("تعذر حفظ وضع الستريك.", show_alert=True)
            return

        with suppress(TelegramBadRequest):
            await _restore_status(callback, bot, repository, streak)
        await callback.answer(
            f"تم تغيير وضع الستريك إلى: {STREAK_MODE_LABELS[mode]}",
            show_alert=True,
        )

    @router.callback_query(F.data.startswith("streak_mode:cancel:"))
    async def cancel_mode(callback: CallbackQuery, bot: Bot) -> None:
        try:
            chat_id = int((callback.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return

        streak = await _owner_streak(repository, callback, chat_id)
        if streak is None:
            await callback.answer("تعذر فتح حالة الستريك.", show_alert=True)
            return

        with suppress(TelegramBadRequest):
            await _restore_status(callback, bot, repository, streak)
        await callback.answer()

    return router
