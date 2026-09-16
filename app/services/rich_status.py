from __future__ import annotations

from aiogram.types import InputRichMessage


def build_streak_rich_message(
    *,
    current: int,
    longest: int,
    completed_days: int,
    break_count: int,
    freeze_count: int,
    last_completed_day: str | None,
) -> InputRichMessage:
    last_day = last_completed_day or "لا يوجد"
    return InputRichMessage(
        html=(
            "<h3>🔥 حالة الستريك</h3>"
            "<details><summary>تفاصيل الستريك 🫠</summary>"
            "<p>"
            f"الستريك الحالي: <b>{current}</b><br/>"
            f"أطول ستريك: <b>{longest}</b><br/>"
            f"إجمالي أيام الستريك: <b>{completed_days}</b><br/>"
            f"عدد مرات انقطاع الستريك: <b>{break_count}</b><br/>"
            f"رصيد الحماية: <b>{freeze_count} 🧊</b><br/>"
            f"آخر يوم تم احتسابه ضمن الستريك: <b>{last_day}</b>"
            "</p></details>"
        ),
        is_rtl=True,
    )
