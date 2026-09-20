from __future__ import annotations

from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputRichMessage

from .rules import BADGES, EVENTS, TASKS, Profile, level_progress


def progress_text(profile: Profile) -> str:
    level, current, needed = level_progress(profile.shared_xp)
    filled = min(10, current * 10 // needed)
    return (
        f"المستوى المشترك {level} 🌟 · Combo x{profile.combo}\n"
        f"{'▰' * filled}{'▱' * (10 - filled)} {current}/{needed} XP\n"
        f"مجموع نقاطكم: {profile.shared_xp} XP"
    )


def navigation(owner: int, chat: int) -> InlineKeyboardMarkup:
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


def rich_buttons(owner: int, chat: int) -> str:
    return "".join(
        f'<tg-button type="callback_data" style="link" data="{button.callback_data}">{button.text}</tg-button>'
        for row in navigation(owner, chat).inline_keyboard[:-1]
        for button in row
    )


def page_text(profile: Profile, state: dict, page: str) -> str:
    if page == "compare":
        first, second = profile.stats["owner"], profile.stats["peer"]
        total = first["contribution"] + second["contribution"]
        ratio = round(first["contribution"] * 100 / total) if total else 50
        lines = ["😆 مقارنة ودية", "إنتوا فريق واحد، مو خصوم!", ""]
        for role, stats, share in [
            ("الأول", first, ratio),
            ("الثاني", second, 100 - ratio),
        ]:
            lines.extend(
                [
                    f"{stats['name'] or 'الطرف ' + role}",
                    f"بدا اليوم: {stats['started']} · تأخر: {stats['late']}",
                    f"أيام شارك بيها: {stats['days']} · إحياء ساهم بيه: {stats['saves']}",
                    f"مساهمته التقريبية: {share}٪",
                    "",
                ]
            )
        lines.extend(
            [
                f"حماية تلقائية أنقذتكم سوا: {profile.automatic_saves}",
                "واضح إنكم متقاربين جدًا 😆"
                if abs(ratio - 50) <= 10
                else "كل واحد إله بصمته، كملوها سوا 🤝",
                f"الإحصائيات من {profile.tracked_since}.",
                "التأخير = أول مشاركة بعد ١٠ بالليل. الإحياء يُحسب للطرفين.",
                "النسبة من أيام المشاركة والمهام، مو عدد الرسائل.",
            ]
        )
        return "\n".join(lines)
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


def rich_page(profile: Profile, state: dict, page: str, owner: int, chat: int):
    text = page_text(profile, state, page)
    title, _, body = text.partition("\n")
    return InputRichMessage(
        html=f"<h1>{escape(title)}</h1><p>{escape(body).replace(chr(10), '<br>')}</p>",
        is_rtl=True,
    )
