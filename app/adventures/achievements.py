"""Achievement definitions and unlock rules for shared adventures."""

BADGES = {
    "together": ("أول مغامرة 🤝", "أكملتوا مجموعة مهام كاملة."),
    "rhythm": ("على نفس الموجة 🎵", "وصلتوا Combo x5."),
    "secret_sync": ("توأم اللحظة 💫", "أول مشاركتين بفارق ٣٠ ثانية أو أقل."),
    "secret_lucky": ("ضيف Jake السري 🍀", "لقيتوا الهدية السرية بيوم المهمة النادرة."),
}


def newly_unlocked(*, combo: int, gap: float | None, event: str, secret_roll: bool) -> list[str]:
    unlocked: list[str] = []
    if combo >= 5:
        unlocked.append("rhythm")
    if gap is not None and gap <= 30:
        unlocked.append("secret_sync")
    if event == "rare" and secret_roll:
        unlocked.append("secret_lucky")
    return unlocked


def add_badge(profile, badge: str) -> bool:
    if badge not in BADGES or badge in profile.badges:
        return False
    profile.badges.append(badge)
    return True
