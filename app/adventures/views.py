from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage

from .achievements import BADGES
from .rules import EVENTS, Profile, level_progress
from .tasks import ALL_TASKS_BONUS_XP, active_task_specs


_NAV_ITEMS = (
    ("tasks", "المهام"),
    ("compare", "المقارنة"),
    ("story", "الستوري"),
    ("badges", "الإنجازات"),
)


def progress_text(profile: Profile) -> str:
    level, current, needed = level_progress(profile.shared_xp)
    filled = min(10, current * 10 // needed)
    return (
        f"المستوى {level} · Combo ×{profile.combo}\n"
        f"{'▰' * filled}{'▱' * (10 - filled)} {current}/{needed} XP · "
        f"الإجمالي {profile.shared_xp}"
    )


def navigation(owner: int, chat: int) -> InlineKeyboardMarkup:
    """Fallback only when Telegram rejects a rich message."""
    rows = [
        [
            InlineKeyboardButton(
                text=label,
                callback_data=f"adv:{action}:{owner}:{chat}",
            )
        ]
        for action, label in _NAV_ITEMS
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text="الحالة",
                callback_data=f"adv:status:{owner}:{chat}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _rich_button(label: str, data: str, *, disabled: bool = False) -> str:
    if disabled:
        return f'<tg-button type="disabled" style="link">{escape(label)}</tg-button>'
    return (
        '<tg-button type="callback_data" style="link" '
        f'data="{escape(data, quote=True)}">{escape(label)}</tg-button>'
    )


def _compact_button_table(buttons: list[str]) -> str:
    rows: list[str] = []
    for index in range(0, len(buttons), 2):
        pair = buttons[index:index + 2]
        cells = "".join(f'<td align="center">{button}</td>' for button in pair)
        if len(pair) == 1:
            cells = f'<td colspan="2" align="center">{pair[0]}</td>'
        rows.append(f"<tr>{cells}</tr>")
    return "<table compact>" + "".join(rows) + "</table>"


def rich_buttons(
    owner: int,
    chat: int,
    *,
    current_page: str | None = None,
    include_status: bool = False,
    include_mode: bool = False,
) -> str:
    buttons: list[str] = []

    if include_mode:
        buttons.append(
            _rich_button(
                "وضع الستريك",
                f"streak_mode:open:{owner}:{chat}",
            )
        )

    for action, label in _NAV_ITEMS:
        buttons.append(
            _rich_button(
                label,
                f"adv:{action}:{owner}:{chat}",
                disabled=action == current_page,
            )
        )

    if include_status:
        buttons.append(
            _rich_button(
                "الحالة",
                f"adv:status:{owner}:{chat}",
                disabled=current_page == "status",
            )
        )

    return _compact_button_table(buttons)


def _compare_comment(ratio: int) -> str:
    if abs(ratio - 50) <= 10:
        return "متقاربين جدًا 😆"
    return "لكل واحد دوره 🤝"


def page_text(profile: Profile, state: dict, page: str) -> str:
    if page == "compare":
        first, second = profile.stats["owner"], profile.stats["peer"]
        total = first["contribution"] + second["contribution"]
        ratio = round(first["contribution"] * 100 / total) if total else 50
        first_name = first["name"] or "الطرف الأول"
        second_name = second["name"] or "الطرف الثاني"
        return "\n".join(
            [
                "مقارنة ودية",
                "",
                f"{first_name} | {second_name}",
                f"بدأ: {first['started']} | {second['started']}",
                f"تأخر: {first['late']} | {second['late']}",
                f"أيام: {first['days']} | {second['days']}",
                f"إحياء: {first['saves']} | {second['saves']}",
                f"مساهمة: {ratio}٪ | {100 - ratio}٪",
                "",
                _compare_comment(ratio),
            ]
        )

    if page == "badges":
        lines = ["الإنجازات", progress_text(profile), ""]
        if profile.badges:
            lines += [f"{BADGES[key][0]} — {BADGES[key][1]}" for key in profile.badges]
        else:
            lines.append("لا يوجد إنجاز ظاهر بعد.")
        return "\n".join(lines)

    lines = ["المهام", progress_text(profile), ""]
    if state.get("event"):
        lines.extend([EVENTS[state["event"]], ""])
    done = set(state.get("done", ()))
    for spec in active_task_specs(state):
        mark = "✓" if spec.key in done else "○"
        multiplier = 2 if state.get("event") == "double" else 1
        lines.append(f"{mark} {spec.label} · {spec.xp * multiplier} XP")
    bonus = ALL_TASKS_BONUS_XP * (2 if state.get("event") == "double" else 1)
    lines.extend(["", f"إكمال الـ6: +{bonus} XP", "تتجدد كل 6 ساعات"])
    return "\n".join(lines)


def _rich_compare(profile: Profile, owner: int, chat: int) -> InputRichMessage:
    first, second = profile.stats["owner"], profile.stats["peer"]
    total = first["contribution"] + second["contribution"]
    ratio = round(first["contribution"] * 100 / total) if total else 50
    first_name = escape(first["name"] or "الطرف الأول")
    second_name = escape(second["name"] or "الطرف الثاني")

    table = (
        "<table compact>"
        "<tr><th>الطرف الأول</th><th>الطرف الثاني</th></tr>"
        f"<tr><td><b>{first_name}</b></td><td><b>{second_name}</b></td></tr>"
        f"<tr><td>بدأ: <b>{first['started']}</b></td><td>بدأ: <b>{second['started']}</b></td></tr>"
        f"<tr><td>تأخر: <b>{first['late']}</b></td><td>تأخر: <b>{second['late']}</b></td></tr>"
        f"<tr><td>أيام: <b>{first['days']}</b></td><td>أيام: <b>{second['days']}</b></td></tr>"
        f"<tr><td>إحياء: <b>{first['saves']}</b></td><td>إحياء: <b>{second['saves']}</b></td></tr>"
        f"<tr><td>مساهمة: <b>{ratio}٪</b></td><td>مساهمة: <b>{100 - ratio}٪</b></td></tr>"
        "</table>"
    )

    return InputRichMessage(
        html=(
            "<h1>مقارنة ودية</h1>"
            "<hr/>"
            + table
            + "<p>"
            f"<b>{escape(_compare_comment(ratio))}</b><br>"
            f"حماية مشتركة: <b>{profile.automatic_saves}</b>"
            "</p>"
            "<details><summary>الحساب</summary>"
            "<p>بدأ = من بدأ اليوم أكثر.<br>"
            "تأخر = أول مشاركة بعد 10 بالليل.<br>"
            "الإحياء محسوب للطرفين.<br>"
            "المساهمة من الأيام والمهام، مو عدد الرسائل وحده.</p>"
            "</details>"
            "<details><summary>الخيارات</summary>"
            + rich_buttons(
                owner,
                chat,
                current_page="compare",
                include_status=True,
            )
            + "</details>"
        ),
        is_rtl=True,
    )


def _rich_tasks(profile: Profile, state: dict, owner: int, chat: int) -> InputRichMessage:
    level, current, needed = level_progress(profile.shared_xp)
    done = set(state.get("done", ()))
    multiplier = 2 if state.get("event") == "double" else 1
    rows: list[str] = []

    for spec in active_task_specs(state):
        mark = "✓" if spec.key in done else "○"
        rows.append(
            "<tr>"
            f"<td align=\"center\">{mark}</td>"
            f"<td>{escape(spec.label)}</td>"
            f"<td align=\"center\"><b>{spec.xp * multiplier}</b></td>"
            "</tr>"
        )

    event = (
        f"<p><b>{escape(EVENTS[state['event']])}</b></p>"
        if state.get("event")
        else ""
    )
    bonus = ALL_TASKS_BONUS_XP * multiplier

    return InputRichMessage(
        html=(
            "<h1>المهام</h1>"
            f"<p><b>المستوى {level}</b> · Combo ×{profile.combo}<br>"
            f"{current}/{needed} XP · الإجمالي <b>{profile.shared_xp}</b></p>"
            + event
            + "<table compact>"
            "<tr><th></th><th>المهمة</th><th>XP</th></tr>"
            + "".join(rows)
            + "</table>"
            f"<footer>إكمال الـ6: +{bonus} XP · تتجدد كل 6 ساعات</footer>"
            "<details><summary>شنو الـCombo؟</summary>"
            "<p>الـCombo يعني شكد يوم ورا بعض تكملون الستريك قبل الساعة 10 بالليل. "
            "خلصتوه قبل 10؟ يزيد ×1. ثاني يوم هم قبل 10؟ يصير ×2، وهكذا؛ "
            "وكل ما يرتفع يعطيكم XP أكثر. إذا خلصتوه بعد 10، فات يوم، "
            "أو استخدمتوا حماية/إحياء، ينقطع ويرجع ×0 وتبدون من جديد.</p>"
            "</details>"
            "<details><summary>الخيارات</summary>"
            + rich_buttons(
                owner,
                chat,
                current_page="tasks",
                include_status=True,
            )
            + "</details>"
        ),
        is_rtl=True,
    )


def _rich_badges(profile: Profile, owner: int, chat: int) -> InputRichMessage:
    if profile.badges:
        badges = "".join(
            f"<li><b>{escape(BADGES[key][0])}</b><br>{escape(BADGES[key][1])}</li>"
            for key in profile.badges
        )
    else:
        badges = "<li>لا يوجد إنجاز ظاهر بعد.</li>"

    return InputRichMessage(
        html=(
            "<h1>الإنجازات</h1>"
            f"<p>{escape(progress_text(profile)).replace(chr(10), '<br>')}</p>"
            "<ul>"
            + badges
            + "</ul>"
            "<footer>بعض الإنجازات مخفية.</footer>"
            "<details><summary>الخيارات</summary>"
            + rich_buttons(
                owner,
                chat,
                current_page="badges",
                include_status=True,
            )
            + "</details>"
        ),
        is_rtl=True,
    )


def rich_story_page(owner: int, chat: int) -> InputRichMessage:
    story_actions = _compact_button_table(
        [
            _rich_button("صورة", f"adv:image:{owner}:{chat}"),
            _rich_button("فيديو · 5 ثواني", f"adv:video5:{owner}:{chat}"),
            _rich_button("فيديو · 10 ثواني", f"adv:video10:{owner}:{chat}"),
        ]
    )

    return InputRichMessage(
        html=(
            "<h1>مشاركة ستوري</h1>"
            "<p>اختار المعاينة. النشر يتم بعد تأكيدك.</p>"
            "<details><summary>النوع</summary>"
            + story_actions
            + "</details>"
            "<details><summary>الخيارات</summary>"
            + rich_buttons(
                owner,
                chat,
                current_page="story",
                include_status=True,
            )
            + "</details>"
        ),
        is_rtl=True,
    )


def rich_page(profile: Profile, state: dict, page: str, owner: int, chat: int):
    if page == "compare":
        return _rich_compare(profile, owner, chat)
    if page == "badges":
        return _rich_badges(profile, owner, chat)
    return _rich_tasks(profile, state, owner, chat)
