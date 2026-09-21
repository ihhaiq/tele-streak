from types import SimpleNamespace

from app.adventures.achievements import BADGES, add_badge, newly_unlocked


def test_achievement_rules_are_separate_and_stable():
    assert len(BADGES) == 4
    assert newly_unlocked(combo=5, gap=30, event="rare", secret_roll=True) == [
        "rhythm", "secret_sync", "secret_lucky"
    ]


def test_add_badge_is_idempotent():
    profile = SimpleNamespace(badges=[])
    assert add_badge(profile, "rhythm") is True
    assert add_badge(profile, "rhythm") is False
    assert add_badge(profile, "unknown") is False
