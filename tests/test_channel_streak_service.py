import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.database.channel_repository import ChannelStreakRepository
from app.handlers.channel import build_router as channel_router
from app.database.engine import Database
from app.services.channel_streak_service import ChannelStreakService
from app.services.channel_permissions import can_manage_channel_story, channel_status_text


def message(day_id=1, author="حسين", bot=False, user_id=7):
    return SimpleNamespace(chat=SimpleNamespace(id=77, type="channel"), sender_chat=None,
        from_user=SimpleNamespace(id=user_id, is_bot=bot, full_name=author), author_signature=author,
        message_id=day_id)


@pytest.mark.asyncio
async def test_channel_one_post_per_day_and_duplicate_does_not_increment(tmp_path):
    path = tmp_path / "db.sqlite"
    db = Database(path)
    await db.init()
    try:
        repo = ChannelStreakRepository(db)
        await repo.activate(77)
        first, completed = await repo.record_post(77, "2026-09-21", "حسين", 7)
        same, duplicate = await asyncio.wait_for(repo.record_post(77, "2026-09-21", "شخص آخر", 8), 2)
        next_day, completed_next = await repo.record_post(77, "2026-09-22", "حسين", 7)
        assert completed and not duplicate and completed_next
        assert same.completed_days == 1 and next_day.current_streak == 2
        assert same.last_completed_by == "حسين" and same.last_completed_by_user_id == 7
    finally:
        await db.close()
    db = Database(path)
    await db.init()
    try:
        saved = await ChannelStreakRepository(db).get(77)
        assert saved.current_streak == 2 and saved.last_completed_by_user_id == 7
        async with db.connect() as conn:
            for table in ("streaks", "adventure_profiles", "adventure_days"):
                assert (await (await conn.execute(f"SELECT COUNT(*) FROM {table}")).fetchone())[0] == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_channel_completion_sends_numbered_sticker_and_first_day_celebration():
    repo = SimpleNamespace(
        activate=AsyncMock(),
        get=AsyncMock(),
    )
    streaks = SimpleNamespace(
        timezone=SimpleNamespace(key="UTC"),
        register_post=AsyncMock(),
    )
    stickers = SimpleNamespace(
        send_channel_success=AsyncMock(),
        send_channel_celebration=AsyncMock(),
    )
    handler = channel_router(repo, streaks, stickers).channel_post.handlers[0].callback
    post = SimpleNamespace(
        text="منشور عادي",
        chat=SimpleNamespace(id=77, type="channel"),
    )

    streaks.register_post.return_value = (
        SimpleNamespace(current_streak=1),
        True,
    )
    await handler(post)
    stickers.send_channel_success.assert_awaited_once_with(
        chat_id=77,
        days=1,
    )
    stickers.send_channel_celebration.assert_awaited_once_with(chat_id=77)

    stickers.send_channel_success.reset_mock()
    stickers.send_channel_celebration.reset_mock()
    streaks.register_post.return_value = (
        SimpleNamespace(current_streak=2),
        True,
    )
    await handler(post)
    stickers.send_channel_success.assert_awaited_once_with(
        chat_id=77,
        days=2,
    )
    stickers.send_channel_celebration.assert_not_awaited()


@pytest.mark.asyncio
async def test_channel_duplicate_post_sends_no_sticker():
    repo = SimpleNamespace(
        activate=AsyncMock(),
        get=AsyncMock(),
    )
    streaks = SimpleNamespace(
        timezone=SimpleNamespace(key="UTC"),
        register_post=AsyncMock(
            return_value=(SimpleNamespace(current_streak=4), False)
        ),
    )
    stickers = SimpleNamespace(
        send_channel_success=AsyncMock(),
        send_channel_celebration=AsyncMock(),
    )
    handler = channel_router(repo, streaks, stickers).channel_post.handlers[0].callback
    post = SimpleNamespace(
        text="منشور ثاني بنفس اليوم",
        chat=SimpleNamespace(id=77, type="channel"),
    )

    await handler(post)

    stickers.send_channel_success.assert_not_awaited()
    stickers.send_channel_celebration.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bot,own_id", [(True, None), (False, 7)])
async def test_channel_bot_post_is_ignored(tmp_path, bot, own_id):
    db = Database(tmp_path / "db.sqlite")
    await db.init()
    try:
        repo = ChannelStreakRepository(db)
        service = ChannelStreakService(repo, "UTC", bot_user_id=own_id)
        await repo.activate(77)
        result, completed = await service.register_post(message(bot=bot))
        assert result is None and not completed
        assert (await repo.get(77)).completed_days == 0
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_channel_service_saves_known_author_and_anonymous_signature(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    await db.init()
    try:
        repo = ChannelStreakRepository(db)
        service = ChannelStreakService(repo, "UTC")
        await repo.activate(77)
        result, completed = await service.register_post(message())
        assert completed and result.last_completed_by_user_id == 7
        anonymous = message(author="توقيع المشرف")
        anonymous.chat.id = 78
        anonymous.from_user = None
        await repo.activate(78)
        result, completed = await service.register_post(anonymous)
        assert completed and result.last_completed_by == "توقيع المشرف"
        assert result.last_completed_by_user_id is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_disabled_and_missing_channels_do_not_deadlock(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    await db.init()
    try:
        repo = ChannelStreakRepository(db)
        result, completed = await asyncio.wait_for(repo.record_post(77, "2026-09-21", "حسين"), 2)
        assert result is None and not completed
        await repo.activate(77)
        await repo.set_enabled(77, False)
        result, completed = await asyncio.wait_for(repo.record_post(77, "2026-09-21", "حسين"), 2)
        assert not completed and result.completed_days == 0
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,can_post,allowed", [
    ("creator", False, True), ("administrator", True, True),
    ("administrator", False, False), ("member", True, False),
    ("left", False, False), ("kicked", False, False),
])
async def test_channel_story_permission_gate(status, can_post, allowed):
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(
        status=status, can_post_stories=can_post)))
    assert await can_manage_channel_story(bot, 77, 7) is allowed
    bot.get_chat_member.assert_awaited_once_with(77, 7)


@pytest.mark.asyncio
async def test_channel_story_role_is_rechecked_and_errors_deny():
    bot = SimpleNamespace(get_chat_member=AsyncMock(side_effect=[
        SimpleNamespace(status="administrator", can_post_stories=True),
        SimpleNamespace(status="member"), RuntimeError("Telegram unavailable"),
    ]))
    assert await can_manage_channel_story(bot, 77, 7)
    assert not await can_manage_channel_story(bot, 77, 7)
    assert not await can_manage_channel_story(bot, 77, 7)


def test_channel_status_does_not_call_yesterdays_post_today(monkeypatch):
    monkeypatch.setattr("app.services.channel_permissions.current_day", lambda _: "2026-09-21")
    streak = SimpleNamespace(is_enabled=True, current_streak=4, longest_streak=9,
        completed_days=12, break_count=1, last_completed_day="2026-09-21",
        last_completed_by="مشرف القناة")
    text = channel_status_text(streak)
    assert "✅ أكمل منشور اليوم: مشرف القناة" in text
    assert "⏳ بانتظار منشور باچر" in text
    streak.last_completed_day = "2026-09-20"
    text = channel_status_text(streak)
    assert "أكمل منشور اليوم" not in text and "⏳ بانتظار منشور اليوم" in text
