from __future__ import annotations

from contextlib import suppress
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.database.activation_repository import StreakActivationRepository
from app.database.repository import Repository, StreakRecord
from app.database.streak_mode_repository import StreakModeRepository
from app.handlers.private import dashboard_keyboard
from app.services.rich_status import protection_text
from app.services.streak_service import StreakService


def _chat_keyboard(streak: StreakRecord) -> InlineKeyboardMarkup:
    enabled = "تعطيل" if streak.is_enabled else "تفعيل"
    notices = "كتم التنبيهات" if streak.notifications_enabled else "تشغيل التنبيهات"
    freeze = "الحماية التلقائية ✅" if streak.auto_freeze else "الحماية التلقائية ❌"
    chat = streak.chat_id
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔥 {enabled}", callback_data=f"chat:enabled:{chat}")],
        [InlineKeyboardButton(text=f"🔔 {notices}", callback_data=f"chat:notifications:{chat}")],
        [InlineKeyboardButton(text=f"🧊 {freeze}", callback_data=f"chat:auto_freeze:{chat}")],
        [InlineKeyboardButton(text="♻️ تصفير الستريك", callback_data=f"chat:reset:{chat}")],
        [InlineKeyboardButton(text="رجوع", callback_data="dash:chats")],
    ])


def _details(streak: StreakRecord) -> str:
    lines = [
        f"🔥 تفاصيل المحادثة {streak.chat_id}",
        "",
        f"الستريك الحالي: {streak.current_streak}",
        f"أطول ستريك: {streak.longest_streak}",
        f"إجمالي أيام الستريك: {streak.completed_days}",
    ]
    if streak.break_count > 0:
        lines.append(f"مرات الانقطاع: {streak.break_count}")
    lines.extend(
        [
            f"الحماية المتاحة: {protection_text(streak.freeze_count)}",
            f"مرات استخدام الحماية: {streak.freezes_used}",
            f"بدأ التتبع: {streak.created_at[:10]}",
        ]
    )
    return "\n".join(lines)


def build_router(
    repository: Repository,
    activations: StreakActivationRepository,
    streaks: StreakService,
    streak_modes: StreakModeRepository,
) -> Router:
    router = Router(name="callbacks")

    @router.callback_query(F.data.startswith("streak_start:approve:"))
    async def approve_streak_start(callback: CallbackQuery, bot: Bot) -> None:
        token = (callback.data or "").rsplit(":", 1)[-1]
        request = await activations.get_request(token)
        if request is None:
            await callback.answer(
                "انتهى هذا الطلب أو تم استخدامه مسبقًا.",
                show_alert=True,
            )
            return

        if callback.from_user.id != request.owner_user_id:
            await callback.answer("هذا الطلب ليس لك.", show_alert=True)
            return

        if await activations.is_active(
            request.business_connection_id,
            request.chat_id,
        ):
            await activations.finish_request(token)
            if callback.message is not None:
                with suppress(TelegramBadRequest):
                    await callback.message.edit_reply_markup(reply_markup=None)
            await callback.answer("الستريك مفعّل بالفعل في هذه المحادثة.", show_alert=True)
            return

        await streaks.start_from_peer_request(
            connection_id=request.business_connection_id,
            chat_id=request.chat_id,
            peer_user_id=request.peer_user_id,
            source_message_id=request.source_message_id,
        )
        await activations.finish_request(token)

        if callback.message is not None:
            with suppress(TelegramBadRequest):
                await callback.message.edit_text(
                    "✅ تم بدء الستريك.\n\n"
                    "تم احتساب رسالة الطرف الثاني، والآن ينتظر البوت رسالتك اليوم."
                )

        with suppress(TelegramBadRequest):
            await bot.send_message(
                chat_id=request.chat_id,
                business_connection_id=request.business_connection_id,
                text=(
                    "🔥 تم قبول بدء الستريك. "
                    "تم احتساب رسالة الطرف الثاني، وبانتظار رسالة صاحب الحساب اليوم."
                ),
            )

        await callback.answer("تم بدء الستريك 🔥")

    @router.callback_query(F.data == "streak:revive")
    async def legacy_revive_streak(callback: CallbackQuery) -> None:
        await callback.answer(
            "تم تغيير طريقة الإحياء. اكتب «احياء الستريك» في المحادثة، "
            "ثم يجب أن يوافق الطرفان من زر الموافقة.",
            show_alert=True,
        )

    @router.callback_query(F.data.startswith("streak_days:"))
    async def streak_days(callback: CallbackQuery) -> None:
        try:
            days = int((callback.data or "").split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer()
            return
        await callback.answer(f"🔥 {days} يوم", show_alert=False)

    @router.callback_query(F.data.startswith("streak_mode:menu:"))
    async def streak_mode_menu(callback: CallbackQuery, bot: Bot) -> None:
        try:
            chat_id = int((callback.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await callback.answer()
            return

        target = await streak_modes.target_for_user(callback.from_user.id, chat_id)
        if target is None:
            await callback.answer("هذا الستريك مو تابع إلك.", show_alert=True)
            return

        current = await streak_modes.get_mode(target.business_connection_id, chat_id)
        labels = {
            "message": "أي رسالة",
            "media": "صورة / فيديو",
            "voice": "بصمة صوتية",
        }
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=("✓ " if current == "message" else "") + "💬 أي رسالة",
                callback_data=f"streak_mode:set:message:{chat_id}",
            )],
            [InlineKeyboardButton(
                text=("✓ " if current == "media" else "") + "🖼 صورة / فيديو",
                callback_data=f"streak_mode:set:media:{chat_id}",
            )],
            [InlineKeyboardButton(
                text=("✓ " if current == "voice" else "") + "🎙 بصمة صوتية",
                callback_data=f"streak_mode:set:voice:{chat_id}",
            )],
        ])
        await bot.send_message(
            chat_id=chat_id,
            business_connection_id=target.business_connection_id,
            text=(
                "⚙️ تغيير وضع الستريك\n\n"
                f"الوضع الحالي: {labels[current]}\n"
                "اختار شنو لازم يرسله كل طرف حتى ينحسب الستريك:"
            ),
            reply_markup=keyboard,
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("streak_mode:set:"))
    async def set_streak_mode(callback: CallbackQuery) -> None:
        try:
            _, _, mode, raw_chat_id = (callback.data or "").split(":", 3)
            chat_id = int(raw_chat_id)
        except (ValueError, IndexError):
            await callback.answer()
            return

        target = await streak_modes.target_for_user(callback.from_user.id, chat_id)
        if target is None:
            await callback.answer("هذا الستريك مو تابع إلك.", show_alert=True)
            return

        labels = {
            "message": "💬 أي رسالة",
            "media": "🖼 صورة / فيديو",
            "voice": "🎙 بصمة صوتية",
        }
        if mode not in labels:
            await callback.answer("وضع غير صالح.", show_alert=True)
            return

        await streak_modes.set_mode(target.business_connection_id, chat_id, mode)
        if callback.message is not None:
            with suppress(TelegramBadRequest):
                await callback.message.edit_text(
                    "⚙️ تغيير وضع الستريك\n\n"
                    f"الوضع الحالي: {labels[mode]}\n"
                    "من هسه هذا النوع فقط ينحسب لإكمال الستريك.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(
                            text=("✓ " if mode == "message" else "") + "💬 أي رسالة",
                            callback_data=f"streak_mode:set:message:{chat_id}",
                        )],
                        [InlineKeyboardButton(
                            text=("✓ " if mode == "media" else "") + "🖼 صورة / فيديو",
                            callback_data=f"streak_mode:set:media:{chat_id}",
                        )],
                        [InlineKeyboardButton(
                            text=("✓ " if mode == "voice" else "") + "🎙 بصمة صوتية",
                            callback_data=f"streak_mode:set:voice:{chat_id}",
                        )],
                    ]),
                )
        await callback.answer("تم تغيير وضع الستريك")

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
            f"مرات استخدام الحماية: {values['freezes_used']}\n"
            f"أفضل محادثة: {values['best_chat_id'] or 'لا توجد'}",
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
