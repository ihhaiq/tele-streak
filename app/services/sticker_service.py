from __future__ import annotations

from aiogram import Bot
from aiogram.types import FSInputFile

from app.database.repository import Repository
from app.keyboards.streak import streak_keyboard
from app.stickers.renderer import StickerRenderer


class StickerService:
    def __init__(self, bot: Bot, repository: Repository, renderer: StickerRenderer):
        self.bot = bot
        self.repository = repository
        self.renderer = renderer

    async def send_status(
        self,
        *,
        connection_id: str,
        chat_id: int,
        current: int,
        longest: int,
        last_completed_day: str | None,
    ) -> None:
        last_day = last_completed_day or "لا يوجد"
        await self.bot.send_message(
            chat_id=chat_id,
            business_connection_id=connection_id,
            text=(
                "🔥 حالة الستريك\n"
                f"الحالي: {current}\n"
                f"الأعلى: {longest}\n"
                f"آخر يوم مكتمل: {last_day}"
            ),
        )

    async def send_success(
        self,
        *,
        connection_id: str,
        chat_id: int,
        pose: str,
        days: int,
    ) -> None:
        path = self.renderer.render(pose, days)
        sent = await self.bot.send_sticker(
            chat_id=chat_id,
            sticker=FSInputFile(path),
            business_connection_id=connection_id,
            reply_markup=streak_keyboard(days),
        )
        await self.repository.set_success_message_id(connection_id, chat_id, sent.message_id)
