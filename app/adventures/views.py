from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage

from .rules import BADGES, EVENTS, TASKS, Profile, level_progress


_NAV_ITEMS = (
    ("tasks", "🎯 مهام ومستوى"),
    ("compare", "😆 مقارنة ودية"),
    ("story", "🎬 مشاركة ستوري"),
    ("badges", "🏅 إنجازاتنا"),
)


def progress_text(profile: Profile) -> str:
    level, current, needed = level_progress(profile.shared_xp)
    filled = min(10, current * 10 // needed)
    return (
        f"المستوى المشترك {level} 🌟 · Combo x{profile.combo}\n"
        f"{'▰' * filled}{'▱' * (10 - filled)} {current}/{needed} XP\n"
        f"مجموع نقاطكم: {profile.shared_xp} XP"
    )


def navigation(owner: int, chat: int) -> InlineKeyboardMarkup:
    """Fallback keyboard used only when Telegram rejects a rich message."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎯 مهام ومستوى", callback_data=f"adv:tasks:{owner}:{chat}"
                ),
                InlineKeyboardButton(
                    text="😆 مقارنة ودية", callback_data=f"adv:compare:{owner}:{chat}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎬 مشاركة ستوري", callback_data=f"adv:story:{owner}:{chat}"
                ),
                InlineKeyboardButton(
                    text="🏅 إنجازاتنا", callback_data=f"adv:badges:{owner}:{chat}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="رجوع للحالة", callback_data=f"adv:status:{owner}:{chat}"
                )
            ],
        ]
    )


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
    """Render one rich action per bullet/line for a calmer details layout."""
    items: list[str] = []
    if include_mode:
        items.append(
            "<li>"
            + _rich_button(
                "⚙️ وضع الستريك",
                f"streak_mode:open:{owner}:{chat}",
            )
            + "</li>"
        )
    for action, label in _NAV_ITEMS:
        items.append(
            "<li>"
            + _rich_button(
                label + (" · أنت هنا" if action == current_page else ""),
                f"adv:{action}:{owner}:{chat}",
                disabled=action == current_page,
            )
            + "</li>"
        )
    if include_status:
        items.append(
            "<li>"
            + _rich_button(
                "↩️ رجوع لحالة الستريك",
                f"adv:status:{owner}:{chat}",
                disabled=current_page == "status",
            )
            + "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def _compare_comment(ratio: int) -> str:
    if abs(ratio - 50) <= 10:
        return "واضح إنكم متقاربين جدًا 😆"
    return "كل واحد إله بصمته، كملوها سوا 🤝"


def page_text(profile: Profile, state: dict, page: str) -> str:
    if page == "compare":
        first, second = profile.stats["owner"], profile.stats["peer"]
        total = first["contribution"] + second["contribution"]
        ratio = round(first["contribution"] * 100 / total) if total else 50
        first_name = first["name"] or "الطرف الأول"
        second_name = second["name"] or "الطرف الثاني"
        return "\n".join(
            [
                "😆 مقارنة ودية",
                "إنتوا فريق واحد، مو خصوم!",
                "",
                f"👤 {first_name}",
                f"• بدأ اليوم: {first['started']}",
                f"• تأخر: {first['late']}",
                f"• أيام شارك بيها: {first['days']}",
                f"• إحياء ساهم بيه: {first['saves']}",
                f"• المساهمة التقريبية: {ratio}٪",
                "",
                f"👤 {second_name}",
                f"• بدأ اليوم: {second['started']}",
                f"• تأخر: {second['late']}",
                f"• أيام شارك بيها: {second['days']}",
                f"• إحياء ساهم بيه: {second['saves']}",
                f"• المساهمة التقريبية: {100 - ratio}٪",
                "",
                f"🤝 حماية تلقائية أنقذتكم سوا: {profile.automatic_saves}",
                _compare_comment(ratio),
                "",
                f"الإحصائيات من {profile.tracked_since}.",
                "التأخير = أول مشاركة بعد ١٠ بالليل. الإحياء يُحسب للطرفين.",
                "النسبة من أيام المشاركة والمهام، مو عدد الرسائل.",
            ]
        )
    if page == "badges":
        lines = ["🏅 إنجازاتنا", progress_text(profile), ""]
        lines += [f"{BADGES[key][0]}\n{BADGES[key][1]}" for key in profile.badges]
        lines.append("بعد أكو مفاجآت مخفية، خليها تجي بوقتها 🤫")
        return "\n\n".join(lines)
    lines = ["🎯 مغامرتكم اليوم", progress_text(profile), ""]
    if state["event"]:
        lines.extend([EVENTS[state["event"]], ""])
    for key in state["tasks"]:
        mark = "✅" if key in state["done"] else "⬜"
        multiplier = 2 if state["event"] == "double" else 1
        lines.append(f"{mark} {TASKS[key][0]} · {TASKS[key][1] * multiplier} XP")
    bonus = 40 if state["event"] == "double" else 20
    lines.extend(
        [
            "",
            f"كل المهام = هدية {bonus} XP إضافية 🎁",
            "إكمال الستريك قبل ١٠ بالليل يرفع الـCombo. التأخير أو يوم فائت يقطعه.",
            "المهام تتجدد بنص الليل حسب توقيتكم. نوع المهمة ما يغيّر وضع الستريك.",
        ]
    )
    return "\n".join(lines)


def _rich_compare(profile: Profile, owner: int, chat: int) -> InputRichMessage:
    first, second = profile.stats["owner"], profile.stats["peer"]
    total = first["contribution"] + second["contribution"]
    ratio = round(first["contribution"] * 100 / total) if total else 50
    first_name = escape(first["name"] or "الطرف الأول")
    second_name = escape(second["name"] or "الطرف الثاني")

    def person(name: str, stats: dict, share: int) -> str:
        return (
            f"<h3>👤 {name}</h3>"
            "<ul>"
            f"<li>بدأ اليوم: <b>{stats['started']}</b></li>"
            f"<li>تأخر: <b>{stats['late']}</b></li>"
            f"<li>أيام شارك بيها: <b>{stats['days']}</b></li>"
            f"<li>إحياء ساهم بيه: <b>{stats['saves']}</b></li>"
            f"<li>المساهمة التقريبية: <b>{share}٪</b></li>"
            "</ul>"
        )

    return InputRichMessage(
        html=(
            "<h1>😆 مقارنة ودية</h1>"
            "<p><b>إنتوا فريق واحد، مو خصوم!</b></p>"
            + person(first_name, first, ratio)
            + "<hr/>"
            + person(second_name, second, 100 - ratio)
            + "<p>"
            f"🤝 حماية تلقائية أنقذتكم سوا: <b>{profile.automatic_saves}</b><br>"
            f"{escape(_compare_comment(ratio))}"
            "</p>"
            "<details><summary>شلون تنحسب؟</summary>"
            "<ul>"
            f"<li>الإحصائيات من <b>{escape(str(profile.tracked_since))}</b>.</li>"
            "<li>التأخير = أول مشاركة بعد ١٠ بالليل.</li>"
            "<li>الإحياء يُحسب للطرفين.</li>"
            "<li>النسبة من أيام المشاركة والمهام، مو عدد الرسائل.</li>"
            "</ul>"
            "</details>"
            "<details><summary>خيارات الستريك</summary>"
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
        mark = "✅" if key in state["done"] else "⬜"
        multiplier = 2 if state["event"] == "double" else 1
        rows.append(
            f"<li>{mark} {escape(TASKS[key][0])} · "
            f"<b>{TASKS[key][1] * multiplier} XP</b></li>"
        )
    event = (
        f"<p>{escape(EVENTS[state['event']])}</p>"
        if state["event"]
        else ""
    )
    bonus = 40 if state["event"] == "double" else 20
    return InputRichMessage(
        html=(
            "<h1>🎯 مغامرتكم اليوم</h1>"
            f"<p>المستوى المشترك <b>{level}</b> 🌟 · Combo x<b>{profile.combo}</b><br>"
            f"{current}/{needed} XP · مجموعكم <b>{profile.shared_xp} XP</b></p>"
            + event
            + "<ul>"
            + "".join(rows)
            + "</ul>"
            f"<p>كل المهام = هدية <b>{bonus} XP</b> إضافية 🎁</p>"
            "<details><summary>ملاحظات</summary>"
            "<ul>"
            "<li>إكمال الستريك قبل ١٠ بالليل يرفع الـCombo.</li>"
            "<li>التأخير أو يوم فائت يقطعه.</li>"
            "<li>المهام تتجدد بنص الليل حسب توقيتكم.</li>"
            "<li>نوع المهمة ما يغيّر وضع الستريك.</li>"
            "</ul>"
            "</details>"
            "<details><summary>خيارات الستريك</summary>"
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
    badges = "".join(
        f"<li><b>{escape(BADGES[key][0])}</b><br>{escape(BADGES[key][1])}</li>"
        for key in profile.badges
    )
    if not badges:
        badges = "<li>بعد ما انفتح إنجاز ظاهر.</li>"
    return InputRichMessage(
        html=(
            "<h1>🏅 إنجازاتنا</h1>"
            f"<p>{escape(progress_text(profile)).replace(chr(10), '<br>')}</p>"
            "<ul>"
            + badges
            + "</ul>"
            "<p>بعد أكو مفاجآت مخفية، خليها تجي بوقتها 🤫</p>"
            "<details><summary>خيارات الستريك</summary>"
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
        + _rich_button("🖼️ صورة ستوري", f"adv:image:{owner}:{chat}")
        + "</li>"
        "<li>"
        + _rich_button("🎬 فيديو ٥ ثواني", f"adv:video5:{owner}:{chat}")
        + "</li>"
        "<li>"
        + _rich_button("🎬 فيديو ١٠ ثواني", f"adv:video10:{owner}:{chat}")
        + "</li>"
        "</ul>"
    )
    return InputRichMessage(
        html=(
            "<h1>🎬 مشاركة ستوري</h1>"
            "<p>اختار نوع المعاينة. بوت الأعمال يرفعها بنفس المحادثة، "
            "وما ينشر شي قبل ما تضغط «نشر الستوري».</p>"
            "<details open><summary>اختيار المعاينة</summary>"
            + story_actions
            + "</details>"
            "<details><summary>خيارات الستريك</summary>"
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
