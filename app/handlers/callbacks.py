from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.database.repository import Repository, StreakRecord
from app.handlers.private import dashboard_keyboard


def _chat_keyboard(streak: StreakRecord) -> InlineKeyboardMarkup:
    enabled = "تعطيل" if streak.is_enabled else "تفعيل"
    notices = "كتم التنبيهات" if streak.notifications_enabled else "تشغيل التنبيهات"
    freeze = "Freeze تلقائي ✅" if streak.auto_freeze else "Freeze تلقائي ❌"
    chat = streak.chat_id
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔥 {enabled}", callback_data=f"chat:enabled:{chat}")],
        [InlineKeyboardButton(text=f"🔔 {notices}", callback_data=f"chat:notifications:{chat}")],
        [InlineKeyboardButton(text=f"🧊 {freeze}", callback_data=f"chat:auto_freeze:{chat}")],
        [InlineKeyboardButton(text="♻️ Reset", callback_data=f"chat:reset:{chat}")],
        [InlineKeyboardButton(text="رجوع", callback_data="dash:chats")],
    ])


def _details(streak: StreakRecord) -> str:
    return (
        f"🔥 تفاصيل المحادثة {streak.chat_id}\n\n"
        f"Current streak: {streak.current_streak}\n"
        f"Longest streak: {streak.longest_streak}\n"
        f"Completed days: {streak.completed_days}\n"
        f"Breaks: {streak.break_count}\n"
        f"Freeze: {streak.freeze_count}\n"
        f"Freeze used: {streak.freezes_used}\n"
        f"Started: {streak.created_at[:10]}"
    )


def build_router(repository: Repository) -> Router:
    router = Router(name="callbacks")

    @router.callback_query(F.data.startswith("streak_days:"))
    async def streak_days(callback: CallbackQuery) -> None:
        try:
            days = int((callback.data or "").split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer()
            return
        await callback.answer(f"🔥 {days} يوم", show_alert=False)

    @router.callback_query(F.data == "dash:stats")
    async def stats(callback: CallbackQuery) -> None:
        if callback.from_user is None or callback.message is None:
            return
        values = await repository.dashboard_stats(callback.from_user.id)
        await callback.message.edit_text(
            "📊 الإحصائيات\n\n"
            f"أعلى حالي: {values['highest_current']}\n"
            f"أعلى تاريخي: {values['highest_ever']}\n"
            f"المحادثات: {values['chats']}\n"
            f"الأيام المكتملة: {values['completed_days']}\n"
            f"Freezes المستخدمة: {values['freezes_used']}",
            reply_markup=dashboard_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data == "dash:chats")
    async def chats(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        rows = await repository.list_owner_streaks(callback.from_user.id)
        keyboard = [[InlineKeyboardButton(
            text=f"🔥 {row.current_streak} • {row.chat_id}",
            callback_data=f"chat:view:{row.chat_id}",
        )] for row in rows[:30]]
        keyboard.append([InlineKeyboardButton(text="رجوع", callback_data="dash:stats")])
        await callback.message.edit_text(
            "🔥 اختر محادثة:" if rows else "لا توجد محادثات متتبعة بعد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        )
        await callback.answer()

    @router.callback_query(F.data == "dash:timezone")
    async def timezone_menu(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        zones = (("بغداد", "Asia/Baghdad"), ("الرياض", "Asia/Riyadh"), ("UTC", "UTC"), ("لندن", "Europe/London"))
        await callback.message.edit_text(
            "🌍 اختر المنطقة الزمنية:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=label, callback_data=f"tz:{zone}")] for label, zone in zones
            ] + [[InlineKeyboardButton(text="رجوع", callback_data="dash:stats")]]),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("tz:"))
    async def set_timezone(callback: CallbackQuery) -> None:
        zone = (callback.data or "")[3:]
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError:
            await callback.answer("منطقة زمنية غير صالحة", show_alert=True)
            return
        count = await repository.set_owner_timezone(callback.from_user.id, zone)
        await callback.answer(f"تم تحديث {count} اتصال إلى {zone}", show_alert=True)

    @router.callback_query(F.data.startswith("chat:"))
    async def manage_chat(callback: CallbackQuery) -> None:
        if callback.message is None:
            return
        try:
            _, action, raw_chat = (callback.data or "").split(":", 2)
            chat_id = int(raw_chat)
        except (ValueError, IndexError):
            await callback.answer()
            return
        if action == "reset":
            await repository.reset_streak(callback.from_user.id, chat_id)
        elif action in {"enabled", "notifications", "auto_freeze"}:
            await repository.toggle_chat_setting(callback.from_user.id, chat_id, action)
        streak = await repository.get_owner_streak(callback.from_user.id, chat_id)
        if streak is None:
            await callback.answer("المحادثة غير موجودة", show_alert=True)
            return
        await callback.message.edit_text(_details(streak), reply_markup=_chat_keyboard(streak))
        await callback.answer("تم الحفظ" if action != "view" else "")

    return router
