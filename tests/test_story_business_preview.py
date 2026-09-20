import asyncio
import base64
import stat
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


def test_youtube_failure_releases_story_rate_limit(tmp_path):
    async def run():
        data = SimpleNamespace(
            claim_story=AsyncMock(return_value=True),
            release_story_claim=AsyncMock(),
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
            side_effect=RuntimeError("تعذر جلب أغنية من YouTube")
        )

        record = SimpleNamespace(
            current_streak=12,
            business_connection_id="bc-1",
            chat_id=20,
        )
        error = await service.prepare_story_preview(
            record,
            10,
            "video5",
        )

        assert "YouTube" in error
        data.release_story_claim.assert_awaited_once()
        bot.send_video.assert_not_awaited()
        bot.send_photo.assert_not_awaited()
        guests.summon.assert_not_awaited()

    asyncio.run(run())


def test_youtube_modes_prioritize_pot_then_fallbacks(tmp_path):
    provider = tmp_path / "provider"
    provider.mkdir()
    music = YouTubeStoryMusic(
        pot_provider_home=provider,
        attempts=1,
    )
    modes = music._modes()
    assert [mode.name for mode in modes] == [
        "mweb-pot",
        "web-safari",
        "android-vr",
        "default",
    ]
    assert modes[0].extractor_args["youtube"]["player_client"] == [
        "mweb",
        "default",
    ]
    assert modes[0].extractor_args["youtubepot-bgutilscript"]["server_home"] == [
        str(provider)
    ]
    assert modes[2].allow_cookies is False


def test_youtube_download_falls_back_after_pot_failure(monkeypatch, tmp_path):
    provider = tmp_path / "provider"
    provider.mkdir()
    music = YouTubeStoryMusic(
        pot_provider_home=provider,
        attempts=1,
    )
    entry = {
        "id": "abc",
        "title": "Artist - Official Audio",
        "duration": 180,
        "webpage_url": "https://www.youtube.com/watch?v=abc",
    }
    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"audio")
    calls = []

    def fake_download(candidate, directory, duration, mode):
        calls.append(mode.name)
        if mode.name == "mweb-pot":
            raise RuntimeError("HTTP Error 403")
        return YouTubeTrack(
            path=clip,
            title=entry["title"],
            webpage_url=entry["webpage_url"],
        )

    monkeypatch.setattr(music, "_download_with_mode", fake_download)
    result = music._download_clip(entry, tmp_path, 5)
    assert result.path == clip
    assert calls[:2] == ["mweb-pot", "web-safari"]


def test_youtube_base_options_skip_cookies_for_android_vr(tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n")
    provider = tmp_path / "provider"
    provider.mkdir()
    music = YouTubeStoryMusic(
        cookie_file=cookie,
        pot_provider_home=provider,
    )
    modes = {mode.name: mode for mode in music._modes()}
    assert "cookiefile" in music._base_options(modes["mweb-pot"])
    assert "cookiefile" not in music._base_options(modes["android-vr"])


def test_youtube_cookies_b64_materialized_securely(tmp_path):
    cookies = "# Netscape HTTP Cookie File\n"
    encoded = base64.b64encode(cookies.encode()).decode()
    provider = tmp_path / "provider"
    provider.mkdir()
    music = YouTubeStoryMusic(
        cookies_b64=encoded,
        pot_provider_home=provider,
    )
    cookie_path = music.cookie_file
    assert cookie_path is not None and cookie_path.is_file()
    assert cookie_path.read_text() == cookies
    assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600
    modes = {mode.name: mode for mode in music._modes()}
    assert music._base_options(modes["mweb-pot"])["cookiefile"] == str(cookie_path)
    assert "cookiefile" not in music._base_options(modes["android-vr"])
    music.close()
    assert not cookie_path.exists()


def test_youtube_cookies_b64_rejects_non_netscape_data():
    encoded = base64.b64encode(b"plain text").decode()
    try:
        YouTubeStoryMusic(cookies_b64=encoded)
    except RuntimeError as error:
        assert "Netscape" in str(error)
    else:
        raise AssertionError("invalid cookie data must be rejected")


def test_youtube_cookies_b64_rejects_invalid_base64():
    try:
        YouTubeStoryMusic(cookies_b64="not-base64")
    except RuntimeError as error:
        assert "Base64" in str(error)
    else:
        raise AssertionError("invalid Base64 must be rejected")


def test_youtube_raw_cookies_materialized_securely(tmp_path):
    cookies = "# Netscape HTTP Cookie File\n"
    provider = tmp_path / "provider"
    provider.mkdir()
    music = YouTubeStoryMusic(
        cookies_raw=cookies,
        pot_provider_home=provider,
    )
    cookie_path = music.cookie_file
    assert cookie_path is not None and cookie_path.is_file()
    assert cookie_path.read_text() == cookies
    assert stat.S_IMODE(cookie_path.stat().st_mode) == 0o600
    modes = {mode.name: mode for mode in music._modes()}
    assert music._base_options(modes["mweb-pot"])["cookiefile"] == str(cookie_path)
    music.close()
    assert not cookie_path.exists()


def test_youtube_raw_cookies_take_priority_over_base64():
    music = YouTubeStoryMusic(
        cookies_raw="# Netscape HTTP Cookie File\n",
        cookies_b64="not-base64",
    )
    try:
        assert music.cookie_file is not None
    finally:
        music.close()


def test_youtube_raw_cookies_reject_non_netscape_data():
    try:
        YouTubeStoryMusic(cookies_raw="plain text")
    except RuntimeError as error:
        assert "Netscape" in str(error)
    else:
        raise AssertionError("invalid raw cookie data must be rejected")
