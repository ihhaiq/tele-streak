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


def test_scheduler_sends_one_warning_with_missing_role():
    today = datetime.now(timezone.utc).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    streak = StreakRecord(
        business_connection_id="bc-1", chat_id=20, peer_user_id=30,
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
    scheduler = StreakScheduler(repository, stickers, warning_hour=0)

    asyncio.run(scheduler.run_once())

    assert repository.claimed
    assert stickers.special[0]["name"] == "warning"
    assert "الطرف الثاني" in stickers.notices[0]["text"]
