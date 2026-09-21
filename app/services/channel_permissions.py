from __future__ import annotations

from aiogram import Bot

from app.services.rich_status import current_day


async def can_manage_channel_story(bot: Bot, channel_id: int, user_id: int) -> bool:
    """Permission gate for a future channel-story transport; never caches roles."""
    try:
        member = await bot.get_chat_member(channel_id, user_id)
    except Exception:
        return False
    if getattr(member, "user", None) and member.user.is_bot:
        return False
    status = getattr(member, "status", None)
    return status == "creator" or (
        status == "administrator" and bool(getattr(member, "can_post_stories", False))
    )


def channel_status_text(streak, timezone_name: str = "Asia/Baghdad") -> str:
    if streak is None or not streak.is_enabled:
        return "🔥 لا يوجد ستريك مفعّل لهذه القناة."
    completed_today = streak.last_completed_day == current_day(timezone_name)
    completed = (
        f"✅ أكمل منشور اليوم: {streak.last_completed_by or 'ناشر القناة'}"
        if completed_today
        else "⏳ بانتظار منشور اليوم"
    )
    return (
        f"🔥 ستريك القناة: {streak.current_streak} يوم\n"
        f"🏆 أطول ستريك: {streak.longest_streak} يوم\n"
        f"✅ الأيام المكتملة: {streak.completed_days}\n"
        f"💔 مرات الانقطاع: {streak.break_count}\n\n{completed}\n"
        + ("⏳ بانتظار منشور باچر" if completed_today else "")
    )
