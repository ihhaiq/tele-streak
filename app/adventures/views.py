from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage

from .rules import BADGES, EVENTS, TASKS, Profile, level_progress


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


def rich_buttons(
    owner: int,
    chat: int,
    *,
    current_page: str | None = None,
    include_status: bool = False,
    include_mode: bool = False,
) -> str:
    items: list[str] = []

    if include_mode:
        items.append(
            "<li>"
            + _rich_button(
                "وضع الستريك",
                f"streak_mode:open:{owner}:{chat}",
            )
            + "</li>"
        )

    for action, label in _NAV_ITEMS:
        items.append(
            "<li>"
            + _rich_button(
                label,
                f"adv:{action}:{owner}:{chat}",
                disabled=action == current_page,
            )
            + "</li>"
        )

    if include_status:
        items.append(
            "<li>"
            + _rich_button(
                "الحالة",
                f"adv:status:{owner}:{chat}",
                disabled=current_page == "status",
            )
            + "</li>"
        )

    return "<ul>" + "".join(items) + "</ul>"


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
                first_name,
                f"• بدأ: {first['started']}",
                f"• تأخر: {first['late']}",
                f"• أيام: {first['days']}",
                f"• إحياء: {first['saves']}",
                f"• مساهمة: {ratio}٪",
                "",
                second_name,
                f"• بدأ: {second['started']}",
                f"• تأخر: {second['late']}",
                f"• أيام: {second['days']}",
                f"• إحياء: {second['saves']}",
                f"• مساهمة: {100 - ratio}٪",
                "",
                _compare_comment(ratio),
                f"حماية مشتركة: {profile.automatic_saves}",
            ]
        )

    if page == "badges":
        lines = ["الإنجازات", progress_text(profile), ""]
        if profile.badges:
            lines += [f"{BADGES[key][0]} — {BADGES[key][1]}" for key in profile.badges]
        else:
            lines.append("لا يوجد إنجاز ظاهر بعد.")
        return "\n".join(lines)

    lines = ["مهام اليوم", progress_text(profile), ""]
    if state["event"]:
        lines.extend([EVENTS[state["event"]], ""])
    for key in state["tasks"]:
        mark = "✓" if key in state["done"] else "○"
        multiplier = 2 if state["event"] == "double" else 1
        lines.append(f"{mark} {TASKS[key][0]} · {TASKS[key][1] * multiplier} XP")
    bonus = 40 if state["event"] == "double" else 20
    lines.extend(["", f"إكمال الكل: +{bonus} XP", "التجدد: 12:00 ص"])
    return "\n".join(lines)


def _rich_compare(profile: Profile, owner: int, chat: int) -> InputRichMessage:
    first, second = profile.stats["owner"], profile.stats["peer"]
    total = first["contribution"] + second["contribution"]
    ratio = round(first["contribution"] * 100 / total) if total else 50
    first_name = escape(first["name"] or "الطرف الأول")
    second_name = escape(second["name"] or "الطرف الثاني")

    def person(name: str, stats: dict, share: int) -> str:
        return (
            f"<h3>{name}</h3>"
            "<ul>"
            f"<li>بدأ: <b>{stats['started']}</b></li>"
            f"<li>تأخر: <b>{stats['late']}</b></li>"
            f"<li>أيام: <b>{stats['days']}</b></li>"
            f"<li>إحياء: <b>{stats['saves']}</b></li>"
            f"<li>مساهمة: <b>{share}٪</b></li>"
            "</ul>"
        )

    return InputRichMessage(
        html=(
            "<h1>مقارنة ودية</h1>"
            + person(first_name, first, ratio)
            + "<hr/>"
            + person(second_name, second, 100 - ratio)
            + "<p>"
            f"<b>{escape(_compare_comment(ratio))}</b><br>"
            f"حماية مشتركة: <b>{profile.automatic_saves}</b>"
            "</p>"
            "<details><summary>الحساب</summary>"
            "<ul>"
            f"<li>منذ: <b>{escape(str(profile.tracked_since))}</b></li>"
            "<li>متأخر = أول مشاركة بعد 10م.</li>"
            "<li>الإحياء للطرفين.</li>"
            "<li>النسبة = الأيام + المهام.</li>"
            "</ul>"
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
    rows: list[str] = []

    for key in state["tasks"]:
        mark = "✓" if key in state["done"] else "○"
        multiplier = 2 if state["event"] == "double" else 1
        rows.append(
            f"<li>{mark} {escape(TASKS[key][0])} · "
            f"<b>{TASKS[key][1] * multiplier} XP</b></li>"
        )

    event = (
        f"<p><b>{escape(EVENTS[state['event']])}</b></p>"
        if state["event"]
        else ""
    )
    bonus = 40 if state["event"] == "double" else 20

    return InputRichMessage(
        html=(
            "<h1>مهام اليوم</h1>"
            f"<p><b>المستوى {level}</b> · Combo ×{profile.combo}<br>"
            f"{current}/{needed} XP · الإجمالي <b>{profile.shared_xp}</b></p>"
            + event
            + "<ul>"
            + "".join(rows)
            + "</ul>"
            f"<footer>إكمال الكل: +{bonus} XP · تتجدد 12:00 ص</footer>"
            "<details><summary>الـCombo</summary>"
            "<p>قبل 10م يرفعه · التأخير أو يوم فائت يقطعه.</p>"
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
    story_actions = (
        "<ul>"
        "<li>"
        + _rich_button("صورة", f"adv:image:{owner}:{chat}")
        + "</li>"
        "<li>"
        + _rich_button("فيديو · 5 ثواني", f"adv:video5:{owner}:{chat}")
        + "</li>"
        "<li>"
        + _rich_button("فيديو · 10 ثواني", f"adv:video10:{owner}:{chat}")
        + "</li>"
        "</ul>"
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
