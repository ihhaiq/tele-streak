from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from app.database.repository import Repository


def build_router(repository: Repository) -> Router:
    router = Router(name="private_bot")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Streak Business Bot is running.\n\n"
            "Connect this bot to your Telegram Business account and grant reply permission. "
            "After that, normal private messages are tracked automatically."
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        connections, streaks = await repository.stats()
        await message.answer(
            f"Active business connections: {connections}\nTracked chats: {streaks}"
        )

    return router
