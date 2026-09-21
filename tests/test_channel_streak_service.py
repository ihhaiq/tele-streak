from types import SimpleNamespace

import pytest

from app.database.channel_repository import ChannelStreakRepository
from app.database.engine import Database
from app.services.channel_streak_service import ChannelStreakService
from app.services.channel_permissions import channel_status_text


def message(day_id=1, author="حسين", bot=False):
    return SimpleNamespace(chat=SimpleNamespace(id=77, type="channel"), sender_chat=None,
        from_user=SimpleNamespace(is_bot=bot, full_name=author), author_signature=author,
        message_id=day_id)


@pytest.mark.asyncio
async def test_channel_one_post_per_day_and_duplicate_does_not_increment(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    await db.init()
    repo = ChannelStreakRepository(db)
    service = ChannelStreakService(repo, "UTC")
    await repo.activate(77)
    first, completed = await repo.record_post(77, "2026-09-21", "حسين")
    same, duplicate = await repo.record_post(77, "2026-09-21", "شخص آخر")
    next_day, completed_next = await repo.record_post(77, "2026-09-22", "حسين")
    assert completed and not duplicate and completed_next
    assert same.completed_days == 1 and next_day.current_streak == 2
    assert next_day.last_completed_by == "حسين"
    await db.close()


@pytest.mark.asyncio
async def test_channel_bot_post_is_ignored(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    await db.init(); repo = ChannelStreakRepository(db)
    service = ChannelStreakService(repo, "UTC"); await repo.activate(77)
    result, completed = await service.register_post(message(bot=True))
    assert result is None and not completed
    await db.close()


def test_channel_status_mentions_completion_signature():
    streak = SimpleNamespace(is_enabled=True, current_streak=4, longest_streak=9,
        completed_days=12, break_count=1, last_completed_day="2026-09-21",
        last_completed_by="مشرف القناة")
    text = channel_status_text(streak)
    assert "✅ أكمل منشور اليوم: مشرف القناة" in text
    assert "⏳ بانتظار المنشور التالي" in text
