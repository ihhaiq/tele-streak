import asyncio
from types import SimpleNamespace

from app.database.activation_repository import StreakActivationRepository
from app.database.engine import Database
from app.database.repository import Repository
from app.services.message_filter import matches_streak_mode
from app.services.rich_status import build_streak_rich_message
from app.services.streak_service import StreakService


def test_rich_mode_button_is_in_footer_inside_details():
    rich = build_streak_rich_message(
        current=7,
        longest=12,
        completed_days=20,
        break_count=1,
        freeze_count=2,
        last_completed_day="2026-09-19",
        streak_mode="media",
        settings_token="AbCd_123456",
    )

    html = rich.html
    assert html is not None
    details_start = html.index("<details>")
    footer_start = html.index("<footer>")
    details_end = html.index("</details>")
    assert details_start < footer_start < details_end
    assert "الوضع الحالي: <b>صورة / فيديو</b>" in html
    assert 'data="streak_mode:open:AbCd_123456"' in html
    assert ">وضع الستريك</tg-button>" in html


def test_streak_mode_content_filter():
    text = SimpleNamespace(photo=None, video=None, voice=None)
    photo = SimpleNamespace(photo=[object()], video=None, voice=None)
    video = SimpleNamespace(photo=None, video=object(), voice=None)
    voice = SimpleNamespace(photo=None, video=None, voice=object())

    assert matches_streak_mode(text, "message")
    assert matches_streak_mode(photo, "media")
    assert matches_streak_mode(video, "media")
    assert not matches_streak_mode(voice, "media")
    assert matches_streak_mode(voice, "voice")
    assert not matches_streak_mode(photo, "voice")


def test_streak_mode_is_persisted_and_authorized(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-mode", 10, None, True)

        await repository.register_activity(
            connection_id="bc-mode",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )

        token = await repository.ensure_streak_settings_token("bc-mode", 20)
        assert token

        settings = await repository.get_streak_settings(token)
        assert settings is not None
        assert settings.mode == "message"
        assert settings.allows(10)
        assert not settings.allows(99)

        assert await repository.set_streak_mode(token, "media")
        streak = await repository.get_streak("bc-mode", 20)
        assert streak is not None
        assert streak.streak_mode == "media"
        assert streak.settings_token == token

        await database.close()

    asyncio.run(scenario())


class _FakePoses:
    def choose(self, days, last_pose):
        return SimpleNamespace(id=f"pose-{days}")


def _message(connection_id, chat_id, sender_id, message_id, *, photo=None, video=None, voice=None):
    return SimpleNamespace(
        business_connection_id=connection_id,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=sender_id),
        message_id=message_id,
        photo=photo,
        video=video,
        voice=voice,
    )


def test_media_mode_ignores_text_and_waits_for_media(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)
        await repository.upsert_connection("bc-media", 10, None, True)
        service = StreakService(
            repository,
            activations,
            "Asia/Baghdad",
            _FakePoses(),
        )

        await service.start_by_owner(_message("bc-media", 20, 10, 1))
        token = await repository.ensure_streak_settings_token("bc-media", 20)
        assert token
        assert await repository.set_streak_mode(token, "media")

        ignored = await service.register_message(
            _message("bc-media", 20, 30, 2)
        )
        assert not ignored.completed
        record = await repository.get_streak("bc-media", 20)
        assert record is not None
        assert record.peer_sent_day is None

        completed = await service.register_message(
            _message("bc-media", 20, 30, 3, photo=[object()])
        )
        assert completed.completed
        assert completed.days == 1

        await database.close()

    asyncio.run(scenario())
