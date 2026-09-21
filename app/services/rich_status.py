from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.types import InputRichMessage

from app.adventures.rules import Profile
from app.adventures.views import progress_text, rich_buttons
from app.streak_modes import MODE_MESSAGE, streak_mode_label

DEFAULT_TIMEZONE = "Asia/Baghdad"


def _timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


def current_day(timezone_name: str | None) -> str:
    return datetime.now(_timezone(timezone_name)).date().isoformat()


def end_of_day_unix(timezone_name: str | None) -> int:
    timezone = _timezone(timezone_name)
    now = datetime.now(timezone)
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone)
    return int(midnight.timestamp())


def remaining_day_text(timezone_name: str | None) -> str:
    timezone = _timezone(timezone_name)
    now = datetime.now(timezone)
    tomorrow = now.date() + timedelta(days=1)
    midnight = datetime.combine(tomorrow, datetime.min.time(), tzinfo=timezone)
    seconds = max(0, int((midnight - now).total_seconds()))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}س {minutes}د"
    return f"{minutes}د"


def protection_text(freeze_count: int) -> str:
    return "🧊" * max(0, min(freeze_count, 3)) if freeze_count > 0 else "لا توجد"


def participation_text(
    *, owner_name: str | None = None, peer_name: str | None = None,
    owner_sent_day: str | None = None, peer_sent_day: str | None = None,
    timezone_name: str | None = DEFAULT_TIMEZONE,
) -> str:
    today = current_day(timezone_name)
    owner, peer = owner_name or "الطرف الأول", peer_name or "الطرف الثاني"
    done = [name for name, day in ((owner, owner_sent_day), (peer, peer_sent_day)) if day == today]
    waiting = [name for name, day in ((owner, owner_sent_day), (peer, peer_sent_day)) if day != today]
    if not waiting:
        return f"✅ اكتمل اليوم بواسطة:\n{owner} و{peer}"
    lines = [f"✅ أكمل اليوم: {done[0]}"] if done else []
    lines.append("⏳ بانتظار: " + " و".join(waiting))
    return "\n".join(lines)


def build_streak_rich_message(
    *,
    current: int,
    longest: int,
    completed_days: int,
    break_count: int,
    freeze_count: int,
    last_completed_day: str | None,
    owner_user_id: int,
    chat_id: int,
    streak_mode: str = MODE_MESSAGE,
    timezone_name: str | None = DEFAULT_TIMEZONE,
    adventure_profile: Profile | None = None,
    owner_name: str | None = None,
    peer_name: str | None = None,
    owner_sent_day: str | None = None,
    peer_sent_day: str | None = None,
) -> InputRichMessage:
    last_day = last_completed_day or "لا يوجد"
    remaining = remaining_day_text(timezone_name)
    midnight_unix = end_of_day_unix(timezone_name)
    mode_label = streak_mode_label(streak_mode)
    participation = participation_text(
        owner_name=owner_name, peer_name=peer_name,
        owner_sent_day=owner_sent_day, peer_sent_day=peer_sent_day,
        timezone_name=timezone_name,
    )

    details = [
        f"<li>الأيام: <b>{completed_days}</b></li>",
        f"<li>آخر نجاح: <b>{escape(last_day)}</b></li>",
        f"<li>الوضع: <b>{escape(mode_label)}</b></li>",
    ]
    if break_count > 0:
        details.append(f"<li>الانقطاعات: <b>{break_count}</b></li>")

    progress = ""
    if adventure_profile is not None:
        progress = (
            "<h3>التقدم</h3><p>"
            + escape(progress_text(adventure_profile)).replace("\n", "<br>")
            + "</p>"
        )

    return InputRichMessage(
        html=(
            "<h1>🔥 الستريك</h1>"
            "<p>"
            f"<b>{current} يوم</b> حاليًا · الأعلى <b>{longest}</b><br>"
            f"الحماية: <b>{protection_text(freeze_count)}</b>"
            "</p>"
            "<p>"
            "<tg-button type=\"disabled\">⏳ "
            f"<tg-time unix=\"{midnight_unix}\" format=\"r\">{remaining}</tg-time>"
            "</tg-button>"
            "</p>"
            "<details><summary>التفاصيل</summary>"
            "<ul>"
            + "".join(details)
            + "</ul>"
            + "<p>" + escape(participation).replace("\n", "<br>") + "</p>"
            + progress
            + "<hr/>"
            "<h3>الخيارات</h3>"
            + rich_buttons(
                owner_user_id,
                chat_id,
                include_mode=True,
            )
            + "</details>"
        ),
        is_rtl=True,
    )


def build_streak_fallback_text(
    *,
    current: int,
    longest: int,
    completed_days: int,
    break_count: int,
    freeze_count: int,
    last_completed_day: str | None,
    streak_mode: str = MODE_MESSAGE,
    timezone_name: str | None = DEFAULT_TIMEZONE,
    adventure_profile: Profile | None = None,
    owner_name: str | None = None,
    peer_name: str | None = None,
    owner_sent_day: str | None = None,
    peer_sent_day: str | None = None,
) -> str:
    lines = [
        "🔥 الستريك",
        f"{current} يوم · الأعلى {longest}",
        f"الحماية: {protection_text(freeze_count)}",
        f"الأيام: {completed_days}",
        f"آخر نجاح: {last_completed_day or 'لا يوجد'}",
        f"الوضع: {streak_mode_label(streak_mode)}",
    ]
    if break_count > 0:
        lines.append(f"الانقطاعات: {break_count}")
    lines.append(participation_text(
        owner_name=owner_name, peer_name=peer_name,
        owner_sent_day=owner_sent_day, peer_sent_day=peer_sent_day,
        timezone_name=timezone_name,
    ))
    lines.append(f"⏳ المتبقي: {remaining_day_text(timezone_name)}")
    if adventure_profile:
        lines.extend(["", progress_text(adventure_profile)])
    return "\n".join(lines)
