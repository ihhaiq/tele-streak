from datetime import date, timedelta


def next_streak(current: int, last_completed: date | None, today: date) -> int:
    return current + 1 if last_completed == today - timedelta(days=1) else 1


def test_consecutive_day():
    today = date(2026, 9, 16)
    assert next_streak(18, date(2026, 9, 15), today) == 19


def test_missed_day_resets():
    today = date(2026, 9, 16)
    assert next_streak(18, date(2026, 9, 14), today) == 1
