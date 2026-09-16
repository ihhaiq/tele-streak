from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram import F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.repository import Repository
from app.services.sticker_service import StickerService


def dashboard_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 الإحصائيات", callback_data="dash:stats")],
        [InlineKeyboardButton(text="🔥 إدارة المحادثات", callback_data="dash:chats")],
        [InlineKeyboardButton(text="🌍 المنطقة الزمنية", callback_data="dash:timezone")],
    ])


def build_router(repository: Repository, stickers: StickerService | None = None) -> Router:
    router = Router(name="private_bot")

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        if message.from_user is None:
            return
        stats = await repository.dashboard_stats(message.from_user.id)
        await message.answer(
            "🔥 لوحة الستريك\n\n"
            f"اتصالات الأعمال النشطة: {stats['connections']}\n"
            f"المحادثات المتتبعة: {stats['chats']}\n"
            f"أعلى ستريك حالي: {stats['highest_current']}",
            reply_markup=dashboard_keyboard(),
        )

    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if message.from_user is None:
            return
        stats = await repository.dashboard_stats(message.from_user.id)
        await message.answer(
            "📊 الإحصائيات\n\n"
            f"أعلى ستريك حالي: {stats['highest_current']}\n"
            f"أعلى ستريك بالتاريخ: {stats['highest_ever']}\n"
            f"المحادثات النشطة: {stats['chats']}\n"
            f"الأيام المكتملة: {stats['completed_days']}\n"
            f"مرات استخدام الحماية: {stats['freezes_used']}",
            reply_markup=dashboard_keyboard(),
        )

    @router.message(Command("pack"))
    @router.message(F.text.in_({"حزمة", "الحزمة"}))
    async def create_pack(message: Message) -> None:
        if stickers is None or message.from_user is None:
            await message.answer("ميزة الحزمة غير مفعّلة حاليًا.")
            return
        configured_owner = stickers.pack.owner_id
        if configured_owner is None or message.from_user.id != configured_owner:
            await message.answer("هذا الأمر متاح للمطوّر فقط.")
            return
        owner_id = configured_owner
        await message.answer(
            "📦 بدأت مزامنة حزمة الستريك باسمك.\n"
            "سيصلك إشعار عند اكتمال الحزم الثلاث؛ يمكنك إغلاق هذه المحادثة أثناء الرفع."
        )

        async def sync() -> None:
            try:
                await stickers.prepare_pack_for_owner(owner_id)
                me = await message.bot.get_me()
                names = stickers.pack.pack_names(me.username or "bot")
                await message.answer(
                    "✅ اكتملت حزمة الستريك.\n\n"
                    + "\n".join(f"https://t.me/addstickers/{name}" for name in names)
                )
            except Exception:
                await message.answer("تعذر إنشاء الحزمة. راجع سجل البوت ثم حاول مرة أخرى.")

        asyncio.create_task(sync(), name=f"pack-command-{owner_id}")

    return router
