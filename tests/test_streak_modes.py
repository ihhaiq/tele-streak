from types import SimpleNamespace

from app.services.message_filter import should_count
from app.services.rich_status import build_streak_rich_message


def _message(**overrides):
    values = {
        "chat": SimpleNamespace(type="private"),
        "sender_business_bot": None,
        "is_from_offline": False,
        "from_user": SimpleNamespace(is_bot=False),
        "text": None,
        "photo": None,
        "video": None,
        "voice": None,
        "video_note": None,
        "sticker": None,
        "animation": None,
        "document": None,
        "audio": None,
        "location": None,
        "contact": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_media_mode_only_counts_photo_or_video():
    assert should_count(_message(photo=[object()]), "media")
    assert should_count(_message(video=object()), "media")
    assert not should_count(_message(text="هلا"), "media")
    assert not should_count(_message(voice=object()), "media")


def test_voice_mode_only_counts_voice_note():
    assert should_count(_message(voice=object()), "voice")
    assert not should_count(_message(audio=object()), "voice")
    assert not should_count(_message(video_note=object()), "voice")
    assert not should_count(_message(text="هلا"), "voice")


def test_default_mode_keeps_normal_messages():
    assert should_count(_message(text="هلا"), "message")
    assert should_count(_message(photo=[object()]), "message")


def test_rich_status_has_mode_button_inside_details():
    rich = build_streak_rich_message(
        current=4,
        longest=7,
        completed_days=9,
        break_count=0,
        freeze_count=3,
        last_completed_day="2026-09-19",
        chat_id=123,
    )
    html = rich.html
    assert "<details>" in html
    assert "<footer>" in html
    assert "وضع الستريك" in html
    assert "streak_mode:menu:123" in html
    assert html.index("<footer>") < html.index("</details>")
