import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.adventure_service import AdventureService
from app.story.youtube_music import YouTubeStoryMusic, YouTubeTrack


def test_business_preview_uploads_media_directly_without_guest_mode(tmp_path):
    async def run():
        media = tmp_path / "story.mp4"
        thumb = tmp_path / "story.jpg"
        media.write_bytes(b"video")
        thumb.write_bytes(b"image")

        request = SimpleNamespace(token="preview_token_123")
        data = SimpleNamespace(
            claim_story=AsyncMock(return_value=True),
            create_story_publish_request=AsyncMock(
                return_value=(request, [])
            ),
            delete_story_publish_request=AsyncMock(return_value=[]),
        )
        bot = SimpleNamespace(
            send_video=AsyncMock(),
            send_photo=AsyncMock(),
        )
        guests = SimpleNamespace(summon=AsyncMock())
        repo = SimpleNamespace(database=None)
        service = AdventureService(
            bot,
            repo,
            guests,
            share_dir=tmp_path / "shared",
        )
        service.data = data
        service._render_story_assets = AsyncMock(
            return_value=(media, thumb, "Real Song")
        )
        service._expire_story_request = AsyncMock()

        record = SimpleNamespace(
            current_streak=12,
            business_connection_id="bc-1",
            chat_id=20,
        )
        error = await service.prepare_story_preview(
            record,
            10,
            "video5",
            reply_to_message_id=99,
        )

        assert error is None
        guests.summon.assert_not_awaited()
        bot.send_photo.assert_not_awaited()
        bot.send_video.assert_awaited_once()
        kwargs = bot.send_video.await_args.kwargs
        assert kwargs["business_connection_id"] == "bc-1"
        assert kwargs["chat_id"] == 20
        assert kwargs["reply_parameters"].message_id == 99
        assert "🎵 Real Song" in kwargs["caption"]
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        assert button.text == "🚀 نشر الستوري"
        assert button.callback_data == "story_publish:preview_token_123"

    asyncio.run(run())


def test_youtube_music_filters_ai_derivatives_and_live_results():
    assert YouTubeStoryMusic._valid_entry(
        {"title": "Artist - Official Audio", "duration": 180}
    )
    for title in (
        "AI Generated Song",
        "Made with Suno",
        "Artist - Karaoke",
        "Artist - Slowed + Reverb",
        "Artist - Remix",
    ):
        assert not YouTubeStoryMusic._valid_entry(
            {"title": title, "duration": 180}
        )
    assert not YouTubeStoryMusic._valid_entry(
        {"title": "Live Stream", "duration": 180, "live_status": "is_live"}
    )


def test_youtube_music_has_no_synthetic_fallback(monkeypatch, tmp_path):
    music = YouTubeStoryMusic(attempts=1)
    monkeypatch.setattr(music, "_search", lambda query: [])
    try:
        music.fetch(tmp_path, 5)
    except RuntimeError as error:
        assert "YouTube" in str(error)
    else:
        raise AssertionError("YouTube failure must not fall back to generated music")


def test_youtube_music_returns_selected_youtube_track(monkeypatch, tmp_path):
    music = YouTubeStoryMusic(attempts=1)
    entry = {
        "id": "abc",
        "title": "Artist - Official Audio",
        "duration": 180,
        "webpage_url": "https://www.youtube.com/watch?v=abc",
    }
    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"audio")
    expected = YouTubeTrack(
        path=clip,
        title=entry["title"],
        webpage_url=entry["webpage_url"],
    )
    monkeypatch.setattr(music, "_search", lambda query: [entry])
    monkeypatch.setattr(
        music,
        "_download_clip",
        lambda candidate, directory, duration: expected,
    )

    result = music.fetch(tmp_path, 10)
    assert result == expected
    assert isinstance(result.path, Path)
