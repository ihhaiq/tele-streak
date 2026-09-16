from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery


def build_router() -> Router:
    router = Router(name="callbacks")

    @router.callback_query(F.data.startswith("streak_days:"))
    async def streak_days(callback: CallbackQuery) -> None:
        try:
            days = int((callback.data or "").split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer()
            return
        await callback.answer(f"{days} day streak", show_alert=False)

    return router
