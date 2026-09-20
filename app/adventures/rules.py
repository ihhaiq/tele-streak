from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

TASKS = {
    "photo": ("صورة من واحد منكم 📷", 15),
    "video": ("فيديو من واحد منكم 🎬", 20),
    "voice": ("بصمة من واحد منكم 🎙", 15),
    "words": ("رسالة من ٣ كلمات أو أكثر 💬", 10),
    "early": ("كملوا الستريك قبل ٦ العصر ☀️", 20),
    "quick": ("مشاركة الطرفين خلال ١٠ دقائق ⚡", 20),
    "peer_first": ("الطرف الثاني يبدي اليوم 😆", 15),
    "rare": ("مهمة نادرة: كل واحد يرسل صورة 🎁", 40),
}
EVENTS = {
    "double": "يوم XP مضاعف ✨",
    "shield": "هدية حماية عند إكمال اليوم 🧊",
    "combo": "مكافأة Combo إضافية 🔥",
    "rare": "ظهرت مهمة نادرة 🎁",
    "fast": "يوم سريع: كملوا خلال ١٠ دقائق ⚡",
    "calm": "يوم هدوء: كملوا قبل ١٠ بالليل 🌙",
}
BADGES = {
    "together": ("أول مغامرة 🤝", "أكملتوا مهام يوم كامل."),
    "rhythm": ("على نفس الموجة 🎵", "وصلتوا Combo x5."),
    "secret_sync": ("توأم اللحظة 💫", "أول مشاركتين بفارق ٣٠ ثانية أو أقل."),
    "secret_lucky": ("ضيف Jake السري 🍀", "لقيتوا الهدية السرية بيوم المهمة النادرة."),
}


def level_progress(xp: int) -> tuple[int, int, int]:
    # كل مستوى يحتاج ١٠٠ نقطة أكثر من السابق.
    level = (1 + math.isqrt(1 + 8 * max(0, xp) // 100)) // 2
    level = max(1, level)
    while 50 * level * (level + 1) <= xp:
        level += 1
    floor = 50 * (level - 1) * level
    return level, xp - floor, 100 * level


@dataclass(frozen=True)
class Activity:
    at: datetime
    role: str
    kind: str = ""
    words: int = 0
    qualifies: bool = True
    name: str = ""


@dataclass
class Profile:
    shared_xp: int = 0
    shared_level: int = 1
    combo: int = 0
    last_good_day: str | None = None
    last_event_day: str | None = None
    stats: dict = field(
        default_factory=lambda: {
            role: dict(started=0, late=0, days=0, saves=0, contribution=0, name="")
            for role in ("owner", "peer")
        }
    )
    badges: list[str] = field(default_factory=list)
    automatic_saves: int = 0
    tracked_since: str = ""


def make_day(day: str, profile: Profile, hour: int, rng=None) -> dict:
    rng = rng or random.SystemRandom()
    pool = ["photo", "video", "voice", "words", "quick", "peer_first"]
    if hour < 18:
        pool.append("early")
    event = ""
    cooled = (
        not profile.last_event_day
        or (date.fromisoformat(day) - date.fromisoformat(profile.last_event_day)).days
        >= 3
    )
    # ٨٠٪ أيام عادية، وفاصل يومين بعد كل حدث.
    if cooled and rng.random() < 0.20:
        roll = rng.random()
        event = (
            "rare"
            if roll < (0.08 if profile.combo >= 5 else 0.03)
            else rng.choice(
                ["double", "shield", "combo", "fast"] + (["calm"] if hour < 22 else [])
            )
        )
        profile.last_event_day = day
    tasks = rng.sample(pool, 2)
    if event == "rare":
        tasks.append("rare")
    return dict(
        tasks=tasks,
        done=[],
        event=event,
        first={},
        photo_roles=[],
        completed=False,
        all_bonus=False,
        notice_count=0,
        latest_notice="",
        secret_roll=rng.random() < 0.05,
    )


def apply_activity(
    profile: Profile,
    state: dict,
    activity: Activity,
    *,
    completed: bool,
    restarted: bool,
    freeze_count: int,
) -> tuple[list[str], bool]:
    day = activity.at.date().isoformat()
    role = activity.role
    stats = profile.stats[role]
    stats["name"] = activity.name[:80] or stats["name"]
    notices = []
    if state["event"] and not state.get("event_noted"):
        notices.append(EVENTS[state["event"]])
        state["event_noted"] = True
    multiplier = 2 if state["event"] == "double" else 1
    gained = 0

    def award(amount: int, label: str, shared: bool = False) -> None:
        nonlocal gained
        amount *= multiplier
        gained += amount
        if shared:
            profile.stats["owner"]["contribution"] += amount / 2
            profile.stats["peer"]["contribution"] += amount / 2
        else:
            stats["contribution"] += amount
        notices.append(f"{label} +{amount} XP")

    if activity.qualifies and role not in state["first"]:
        if not state["first"]:
            if not state.get("starter_counted"):
                stats["started"] += 1
                state["starter_counted"] = True
        state["first"][role] = activity.at.timestamp()
        counted = state.setdefault("counted_roles", [])
        if role not in counted:
            counted.append(role)
            stats["days"] += 1
            stats["contribution"] += 10
            stats["late"] += int(activity.at.hour >= 22)
    first = state["first"]
    gap = abs(first["owner"] - first["peer"]) if len(first) == 2 else None
    if activity.kind == "photo" and role not in state["photo_roles"]:
        state["photo_roles"].append(role)
    conditions = {
        "photo": activity.kind == "photo",
        "video": activity.kind == "video",
        "voice": activity.kind == "voice",
        "words": activity.words >= 3,
        "peer_first": bool(first) and min(first, key=first.get) == "peer",
        "early": completed and activity.at.hour < 18,
        "quick": completed and gap is not None and gap <= 600,
        "rare": len(state["photo_roles"]) == 2,
    }
    for task in state["tasks"]:
        if task not in state["done"] and conditions[task]:
            state["done"].append(task)
            award(
                TASKS[task][1],
                f"تمت المهمة اليومية 🎯 {TASKS[task][0]}",
                shared=task in {"early", "quick", "rare"},
            )
    if len(state["done"]) == len(state["tasks"]) and not state["all_bonus"]:
        state["all_bonus"] = True
        award(20, "خلصتوا كل المهام! 🎉", shared=True)
        if "together" not in profile.badges:
            profile.badges.append("together")
            notices.append("فتحتوا إنجاز: أول مغامرة 🤝")

    shield = False
    if completed and not state["completed"]:
        state["completed"] = True
        award(20, "اكتمل يومكم 🤝", shared=True)
        yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        good = activity.at.hour < 22
        if good:
            profile.combo = (
                profile.combo + 1
                if profile.last_good_day == yesterday and not restarted
                else 1
            )
            profile.last_good_day = day
            award(min(profile.combo, 5) * 5, f"Combo x{profile.combo} 🔥", shared=True)
        else:
            profile.combo = 0
            profile.last_good_day = None
            notices.append("الـCombo يرتاح اليوم، باچر نرجع أقوى 😌")
        event = state["event"]
        if event == "shield":
            if freeze_count < 3:
                shield = True
                notices.append("Jake جابلكم حماية مجانية 🧊")
            else:
                award(20, "الحماية كاملة، بدلها هدية نقاط 🎁", shared=True)
        elif event == "combo" and profile.combo >= 2:
            award(25, "هدية الـCombo 🔥", shared=True)
        elif event == "fast" and gap is not None and gap <= 600:
            award(30, "فريق الصاروخ ⚡", shared=True)
        elif event == "calm" and good:
            award(20, "يوم هادي وحلو 🌙", shared=True)
        unlock = []
        if profile.combo >= 5:
            unlock.append("rhythm")
        if gap is not None and gap <= 30:
            unlock.append("secret_sync")
        if event == "rare" and state["secret_roll"]:
            unlock.append("secret_lucky")
        for badge in unlock:
            if badge not in profile.badges:
                profile.badges.append(badge)
                award(30, f"مفاجأة! {BADGES[badge][0]}", shared=True)
    previous_level = profile.shared_level
    profile.shared_xp += gained
    profile.shared_level = level_progress(profile.shared_xp)[0]
    if profile.shared_level > previous_level:
        notices.append(f"مستواكم صار {profile.shared_level}! 🚀")
    return notices, shield
