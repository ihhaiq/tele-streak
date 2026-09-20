from datetime import datetime, timedelta, timezone
import asyncio

from app.database.repository import StreakRecord
from app.services.scheduler import StreakScheduler


class FakeRepository:
    def __init__(self, streak):
        self.streak = streak
        self.claimed = False

    async def list_monitorable_streaks(self):
        return [(self.streak, "UTC")]

    async def claim_warning(self, *args):
        self.claimed = True
        return True

    async def process_missed_day(self, **kwargs):
        return None

    async def cleanup_processed_messages(self):
        return 0


class FakeStickers:
    def __init__(self):
        self.special = []
        self.notices = []
    async def send_special(self, **kwargs):
        self.special.append(kwargs)

    async def send_notice_text(self, **kwargs):
        self.notices.append(kwargs)


class FakeGuests:
    def __init__(self, succeeds=True):
        self.succeeds = succeeds
        self.events = []

    async def summon(self, **kwargs):
        self.events.append(kwargs)
        return self.succeeds


def test_scheduler_sends_warning_through_guest_mode():
    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    streak = StreakRecord(
        business_connection_id="bc-1", chat_id=20, peer_user_id=30, streak_mode="message",
        current_streak=5, longest_streak=5, completed_days=5,
        break_count=0, last_completed_day=yesterday,
        owner_sent_day=today.isoformat(), peer_sent_day=None,
        last_pose="pose", last_success_message_id=None,
        last_warning_day=None, last_broken_day=None,
        notifications_enabled=True, is_enabled=True,
        freeze_count=1, auto_freeze=True, freezes_used=0,
        created_at="2026-09-01", updated_at="2026-09-16",
    )
    repository = FakeRepository(streak)
    stickers = FakeStickers()
    guests = FakeGuests()
    scheduler = StreakScheduler(repository, stickers, guests, warning_hour=0)

    asyncio.run(scheduler.run_once())

    assert repository.claimed
    assert [event["event"] for event in guests.events] == [
        "warning_sticker",
        "warning_notice",
    ]
    assert stickers.special == []
    assert stickers.notices == []


def test_broken_streak_starts_guest_only_broken_flow():
    class BrokenRepository(FakeRepository):
        async def process_missed_day(self, **kwargs):
            return "broken"

    today = datetime.now(timezone.utc).date()
    day_before_yesterday = (today - timedelta(days=2)).isoformat()
    streak = StreakRecord(
        business_connection_id="bc-1", chat_id=20, peer_user_id=30, streak_mode="message",
        current_streak=5, longest_streak=5, completed_days=5,
        break_count=0, last_completed_day=day_before_yesterday,
        owner_sent_day=None, peer_sent_day=None,
        last_pose="pose", last_success_message_id=None,
        last_warning_day=None, last_broken_day=None,
        notifications_enabled=True, is_enabled=True,
        freeze_count=0, auto_freeze=False, freezes_used=0,
        created_at="2026-09-01", updated_at="2026-09-16",
    )
    repository = BrokenRepository(streak)
    stickers = FakeStickers()
    guests = FakeGuests()
    scheduler = StreakScheduler(repository, stickers, guests, warning_hour=24)

    asyncio.run(scheduler.run_once())

    assert guests.events == [
        {
            "event": "broken_notice",
            "connection_id": "bc-1",
            "chat_id": 20,
        },
    ]
    assert stickers.special == []
    assert stickers.notices == []


def test_broken_streak_does_not_send_business_fallback_if_guest_is_unavailable():
    class BrokenRepository(FakeRepository):
        async def process_missed_day(self, **kwargs):
            return "broken"

    today = datetime.now(timezone.utc).date()
    day_before_yesterday = (today - timedelta(days=2)).isoformat()
    streak = StreakRecord(
        business_connection_id="bc-1", chat_id=20, peer_user_id=30, streak_mode="message",
        current_streak=5, longest_streak=5, completed_days=5,
        break_count=0, last_completed_day=day_before_yesterday,
        owner_sent_day=None, peer_sent_day=None,
        last_pose="pose", last_success_message_id=None,
        last_warning_day=None, last_broken_day=None,
        notifications_enabled=True, is_enabled=True,
        freeze_count=0, auto_freeze=False, freezes_used=0,
        created_at="2026-09-01", updated_at="2026-09-16",
    )
    repository = BrokenRepository(streak)
    stickers = FakeStickers()
    guests = FakeGuests(succeeds=False)
    scheduler = StreakScheduler(repository, stickers, guests, warning_hour=24)

    asyncio.run(scheduler.run_once())

    assert guests.events == [
        {
            "event": "broken_notice",
            "connection_id": "bc-1",
            "chat_id": 20,
        },
    ]
    assert stickers.special == []
    assert stickers.notices == []

