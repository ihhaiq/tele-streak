from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.repository import Repository


def dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 الإحصائيات", callback_data="dash:stats")],
        [InlineKeyboardButton(text="🔥 إدارة المحادثات", callback_data="dash:chats")],
        [InlineKeyboardButton(text="🌍 المنطقة الزمنية", callback_data="dash:timezone")],
    ])


def build_router(repository: Repository) -> Router:
    router = Router(name="private_bot")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        stats = await repository.dashboard_stats(message.from_user.id)
        await message.answer(
            "🔥 لوحة Streak\n\n"
            f"اتصالات Business النشطة: {stats['connections']}\n"
            f"المحادثات المتتبعة: {stats['chats']}\n"
            f"أعلى Streak حالي: {stats['highest_current']}",
            reply_markup=dashboard_keyboard(),
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if message.from_user is None:
            return
        stats = await repository.dashboard_stats(message.from_user.id)
        await message.answer(
            "📊 الإحصائيات\n\n"
            f"أعلى Streak حالي: {stats['highest_current']}\n"
            f"أعلى Streak بالتاريخ: {stats['highest_ever']}\n"
            f"المحادثات النشطة: {stats['chats']}\n"
            f"الأيام المكتملة: {stats['completed_days']}\n"
            f"مرات استخدام Freeze: {stats['freezes_used']}",
            reply_markup=dashboard_keyboard(),
        )

    return router
