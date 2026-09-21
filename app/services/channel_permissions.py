from __future__ import annotations

from aiogram import Bot


MANAGER_STATUSES = {"creator", "administrator"}


async def can_manage_channel_story(bot: Bot, channel_id: int, user_id: int) -> bool:
    """Check the human's channel role before accepting preview/publish callbacks.

    A callback user is never trusted from the button token alone. Telegram may
    change the member role after a preview was created, so this check is made
    again immediately before publishing.
    """
    try:
        member = await bot.get_chat_member(channel_id, user_id)
    except Exception:
        return False
    return getattr(member, "status", None) in MANAGER_STATUSES


def channel_status_text(streak) -> str:
    if streak is None or not streak.is_enabled:
        return "🔥 لا يوجد ستريك مفعّل لهذه القناة."
    completed = (
        f"✅ أكمل منشور اليوم: {streak.last_completed_by}"
        if streak.last_completed_day
        else "⏳ بانتظار المنشور الأول"
    )
    return (
        f"🔥 ستريك القناة: {streak.current_streak} يوم\n"
        f"🏆 أطول ستريك: {streak.longest_streak} يوم\n"
        f"✅ الأيام المكتملة: {streak.completed_days}\n"
        f"💔 مرات الانقطاع: {streak.break_count}\n\n{completed}\n"
        "⏳ بانتظار المنشور التالي"
    )
