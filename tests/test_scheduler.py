from datetime import datetime, timedelta, timezone
import asyncio

from app.database.repository import StreakRecord
from app.services.scheduler import StreakScheduler


class FakeRepository:
    def __init__(self, streak):
        self.streak = streak
        self.claimed = False

    async def participant_status(self, streak):
        return dict(owner_sent_day=streak.owner_sent_day, peer_sent_day=streak.peer_sent_day)

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
        self.channel_warnings = []
        self.channel_broken = []
    async def send_special(self, **kwargs):
        self.special.append(kwargs)

    async def send_notice_text(self, **kwargs):
        self.notices.append(kwargs)

    async def send_channel_warning_notice(self, **kwargs):
        self.channel_warnings.append(kwargs)

    async def send_channel_broken_notice(self, **kwargs):
        self.channel_broken.append(kwargs)


class TransportFailure:
    transport_unavailable = True

    def __bool__(self):
        return False

    def __str__(self):
        return "False"


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



def test_scheduler_does_not_fallback_after_business_transport_failure():
    class TransportGuests(FakeGuests):
        async def summon(self, **kwargs):
            self.events.append(kwargs)
            return TransportFailure()

    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    streak = StreakRecord(
        business_connection_id="bc-old", chat_id=20, peer_user_id=30, streak_mode="message",
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
    guests = TransportGuests()
    scheduler = StreakScheduler(repository, stickers, guests, warning_hour=0)

    asyncio.run(scheduler.run_once())

    assert [event["event"] for event in guests.events] == ["warning_sticker"]
    assert stickers.special == []
    assert stickers.notices == []



class FakeChannelRepository:
    def __init__(self, streaks):
        self.streaks = streaks
        self.warning_claims = []
        self.break_calls = []

    async def list_monitorable(self):
        return self.streaks

    async def claim_warning(self, channel_id, day):
        self.warning_claims.append((channel_id, day))
        return True

    async def process_missed_day(self, channel_id, **kwargs):
        self.break_calls.append((channel_id, kwargs))
        return True


def _quiet_private_streak(today):
    return StreakRecord(
        business_connection_id="bc-1", chat_id=20, peer_user_id=30, streak_mode="message",
        current_streak=1, longest_streak=1, completed_days=1,
        break_count=0, last_completed_day=today,
        owner_sent_day=today, peer_sent_day=today,
        last_pose="pose", last_success_message_id=None,
        last_warning_day=today, last_broken_day=None,
        notifications_enabled=True, is_enabled=True,
        freeze_count=1, auto_freeze=True, freezes_used=0,
        created_at="2026-09-01", updated_at="2026-09-16",
    )


def test_scheduler_sends_channel_warning_once_claimed():
    today = datetime.now(timezone.utc).date().isoformat()
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    private = _quiet_private_streak(today)
    channel = type("Channel", (), {
        "channel_id": 77,
        "last_completed_day": yesterday,
        "last_warning_day": None,
    })()
    channels = FakeChannelRepository([channel])
    stickers = FakeStickers()
    scheduler = StreakScheduler(
        FakeRepository(private),
        stickers,
        FakeGuests(),
        channel_repository=channels,
        channel_timezone_name="UTC",
        warning_hour=0,
    )

    asyncio.run(scheduler.run_once())

    assert channels.warning_claims == [(77, today)]
    assert stickers.channel_warnings == [{"chat_id": 77}]
    assert channels.break_calls == []


def test_scheduler_breaks_expired_channel_and_sends_death_notice():
    today_date = datetime.now(timezone.utc).date()
    today = today_date.isoformat()
    old_day = (today_date - timedelta(days=2)).isoformat()
    private = _quiet_private_streak(today)
    channel = type("Channel", (), {
        "channel_id": 77,
        "last_completed_day": old_day,
        "last_warning_day": None,
    })()
    channels = FakeChannelRepository([channel])
    stickers = FakeStickers()
    scheduler = StreakScheduler(
        FakeRepository(private),
        stickers,
        FakeGuests(),
        channel_repository=channels,
        channel_timezone_name="UTC",
        warning_hour=24,
    )

    asyncio.run(scheduler.run_once())

    assert len(channels.break_calls) == 1
    assert channels.break_calls[0][0] == 77
    assert stickers.channel_broken == [{"chat_id": 77}]
    assert stickers.channel_warnings == []
