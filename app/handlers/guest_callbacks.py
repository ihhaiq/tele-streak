from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery

from app.database.guest_action_repository import GuestActionRepository
from app.database.repository import Repository
from app.services.rich_status import protection_text


def build_router(
    repository: Repository,
    actions: GuestActionRepository,
) -> Router:
    router = Router(name="guest_callbacks")

    @router.callback_query(F.data.startswith("streak:revive:"))
    async def revive_guest_streak(callback: CallbackQuery, bot: Bot) -> None:
        token = (callback.data or "").rsplit(":", 1)[-1]
        action = await actions.consume(token, action="revive")
        if action is None:
            await callback.answer(
                "انتهت صلاحية زر الإحياء أو تم استخدامه مسبقًا.",
                show_alert=True,
            )
            return

        result = await repository.revive_streak(
            action.business_connection_id,
            action.chat_id,
        )
        if result.status == "no_balance":
            await callback.answer("نفد رصيد الحماية 🧊", show_alert=True)
            return
        if result.status != "revived":
            await callback.answer(
                "لا يمكن إحياء هذا الستريك الآن.",
                show_alert=True,
            )
            return

        if callback.inline_message_id:
            with suppress(TelegramBadRequest):
                await bot.edit_message_reply_markup(
                    inline_message_id=callback.inline_message_id,
                    reply_markup=None,
                )

        await callback.answer(
            f"تم إحياء الستريك 🔥 عاد إلى {result.streak}. "
            f"المتبقي: {protection_text(result.freeze_count)}",
            show_alert=True,
        )

    return router
