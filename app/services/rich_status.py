from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram.types import InputRichMessage

from app.services.message_filter import STREAK_MODE_LABELS

DEFAULT_TIMEZONE = "Asia/Baghdad"


def _timezone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TIMEZONE)


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


def build_streak_rich_message(
    *,
    current: int,
    longest: int,
    completed_days: int,
    break_count: int,
    freeze_count: int,
    last_completed_day: str | None,
    chat_id: int,
    streak_mode: str = "message",
    timezone_name: str | None = DEFAULT_TIMEZONE,
) -> InputRichMessage:
    last_day = last_completed_day or "لا يوجد"
    breaks = (
        f"عدد مرات انقطاع الستريك: <b>{break_count}</b><br>"
        if break_count > 0
        else ""
    )
    remaining = remaining_day_text(timezone_name)
    midnight_unix = end_of_day_unix(timezone_name)
    mode_label = STREAK_MODE_LABELS.get(streak_mode, STREAK_MODE_LABELS["message"])
    return InputRichMessage(
        html=(
            "<h1>🔥 حالة الستريك</h1>"
            "<details><summary>تفاصيل الستريك 🫠</summary>"
            "<p>"
            f"الستريك الحالي: <b>{current}</b><br>"
            f"أطول ستريك: <b>{longest}</b><br>"
            f"إجمالي أيام الستريك: <b>{completed_days}</b><br>"
            f"{breaks}"
            f"الحماية المتاحة: <b>{protection_text(freeze_count)}</b><br>"
            f"آخر يوم ناجح: <b>{last_day}</b><br>"
            f"وضع الستريك: <b>{mode_label}</b>"
            "</p>"
            "<footer>"
            f"<tg-button type=\"callback_data\" style=\"link\" data=\"streak_mode:open:{chat_id}\">"
            "وضع الستريك"
            "</tg-button>"
            "</footer>"
            "</details>"
            "<p>"
            "<tg-button type=\"disabled\">⏳ "
            f"<tg-time unix=\"{midnight_unix}\" format=\"r\">{remaining}</tg-time>"
            "</tg-button>"
            "</p>"
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
    streak_mode: str = "message",
    timezone_name: str | None = DEFAULT_TIMEZONE,
) -> str:
    lines = [
        "🔥 حالة الستريك",
        "",
        f"الستريك الحالي: {current}",
        f"أطول ستريك: {longest}",
        f"إجمالي أيام الستريك: {completed_days}",
    ]
    if break_count > 0:
        lines.append(f"عدد مرات انقطاع الستريك: {break_count}")
    lines.extend(
        [
            f"الحماية المتاحة: {protection_text(freeze_count)}",
            f"آخر يوم ناجح: {last_completed_day or 'لا يوجد'}",
            f"وضع الستريك: {STREAK_MODE_LABELS.get(streak_mode, STREAK_MODE_LABELS['message'])}",
            f"⏳ المتبقي لنهاية اليوم: {remaining_day_text(timezone_name)}",
        ]
    )
    return "\n".join(lines)
