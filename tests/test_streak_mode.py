import asyncio
from types import SimpleNamespace

import pytest

from app.database.engine import Database
from app.database.repository import Repository
from app.handlers.streak_mode import build_mode_menu
from app.services.message_filter import matches_streak_mode
from app.services.rich_status import build_streak_rich_message
from app.streak_modes import (
    MODE_MESSAGE,
    MODE_PHOTO_VIDEO,
    MODE_VOICE,
)


def fake_message(*, text=None, photo=None, video=None, voice=None):
    return SimpleNamespace(text=text, photo=photo, video=video, voice=voice)


def test_mode_filter_accepts_only_selected_content():
    photo = fake_message(photo=[object()])
    video = fake_message(video=object())
    voice = fake_message(voice=object())
    text = fake_message(text="هلا")

    assert matches_streak_mode(text, MODE_MESSAGE)
    assert not matches_streak_mode(photo, MODE_MESSAGE)

    assert matches_streak_mode(photo, MODE_PHOTO_VIDEO)
    assert matches_streak_mode(video, MODE_PHOTO_VIDEO)
    assert not matches_streak_mode(voice, MODE_PHOTO_VIDEO)
    assert not matches_streak_mode(text, MODE_PHOTO_VIDEO)

    assert matches_streak_mode(voice, MODE_VOICE)
    assert not matches_streak_mode(photo, MODE_VOICE)
    assert not matches_streak_mode(text, MODE_VOICE)


def test_status_places_mode_button_in_details_footer():
    rich = build_streak_rich_message(
        current=7,
        longest=12,
        completed_days=20,
        break_count=1,
        freeze_count=3,
        last_completed_day="2026-09-19",
        owner_user_id=777,
        chat_id=123456,
        streak_mode=MODE_PHOTO_VIDEO,
    )

    assert rich.is_rtl is True
    assert rich.html is not None
    assert "<details>" in rich.html
    assert "<footer>" in rich.html
    assert 'data="streak_mode:open:777:123456"' in rich.html
    assert ">وضع الستريك</tg-button>" in rich.html
    assert "صورة / فيديو" in rich.html


def test_mode_menu_marks_current_mode_and_has_all_choices():
    rich = build_mode_menu(777, 555, MODE_VOICE)

    assert rich.html is not None
    assert "✓ بصمة صوتية" in rich.html
    assert "streak_mode:set:message:777:555" in rich.html
    assert "streak_mode:set:photo_video:777:555" in rich.html
    assert "streak_mode:cancel:777:555" in rich.html


def test_repository_persists_streak_mode_across_restart(tmp_path):
    async def scenario():
        path = tmp_path / "streak.db"
        database = Database(path)
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )
        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.streak_mode == MODE_MESSAGE

        changed = await repository.set_streak_mode(
            10, "bc-1", 20, MODE_VOICE, "2026-09-20"
        )
        assert changed is not None
        assert changed.streak_mode == MODE_VOICE
        assert changed.owner_sent_day is None
        assert changed.peer_sent_day is None
        await database.close()

        reopened = Database(path)
        await reopened.init()
        repository = Repository(reopened)
        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.streak_mode == MODE_VOICE
        await reopened.close()

    asyncio.run(scenario())


def test_repository_rejects_unknown_streak_mode(tmp_path):
    async def scenario():
        database = Database(tmp_path / "streak.db")
        await database.init()
        repository = Repository(database)
        with pytest.raises(ValueError):
            await repository.set_streak_mode(
                1, "bc-1", 2, "unknown", "2026-09-20"
            )
        await database.close()

    asyncio.run(scenario())


def test_mode_change_is_scoped_to_one_business_connection(tmp_path):
    async def scenario():
        database = Database(tmp_path / "streak.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)
        await repository.upsert_connection("bc-2", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )
        await repository.register_activity(
            connection_id="bc-2",
            chat_id=20,
            message_id=2,
            peer_user_id=None,
            role="owner",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )

        changed = await repository.set_streak_mode(
            10, "bc-1", 20, MODE_VOICE, "2026-09-20"
        )
        assert changed is not None
        assert changed.business_connection_id == "bc-1"
        assert changed.streak_mode == MODE_VOICE

        other = await repository.get_streak("bc-2", 20)
        assert other is not None
        assert other.streak_mode == MODE_MESSAGE
        await database.close()

    asyncio.run(scenario())


def test_mode_change_keeps_already_completed_day(tmp_path):
    async def scenario():
        database = Database(tmp_path / "streak.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )
        completed = await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )
        assert completed.completed

        changed = await repository.set_streak_mode(
            10, "bc-1", 20, MODE_PHOTO_VIDEO, "2026-09-20"
        )
        assert changed is not None
        assert changed.streak_mode == MODE_PHOTO_VIDEO
        assert changed.last_completed_day == "2026-09-20"
        assert changed.owner_sent_day == "2026-09-20"
        assert changed.peer_sent_day == "2026-09-20"
        await database.close()

    asyncio.run(scenario())
