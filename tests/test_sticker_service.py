import asyncio
from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest

from app.services.rich_status import build_streak_rich_message
from app.services.sticker_service import StickerService, resolve_sticker_path


class FakeRenderer:
    def __init__(self, rendered: Path):
        self.rendered = rendered
        self.calls: list[tuple[str, int]] = []

    def render(self, pose_id: str, days: int) -> Path:
        self.calls.append((pose_id, days))
        return self.rendered


def test_ready_sticker_is_preferred(tmp_path):
    ready = tmp_path / "ready"
    ready.mkdir()
    expected = ready / "007.webp"
    expected.touch()
    renderer = FakeRenderer(tmp_path / "fallback.webp")

    result = resolve_sticker_path(ready, renderer, "flag", 7)

    assert result == expected
    assert renderer.calls == []


def test_renderer_is_used_when_ready_sticker_is_missing(tmp_path):
    renderer = FakeRenderer(tmp_path / "fallback.webp")

    result = resolve_sticker_path(tmp_path, renderer, "flag", 61)

    assert result == renderer.rendered
    assert renderer.calls == [("flag", 61)]


def test_non_positive_days_are_rejected(tmp_path):
    renderer = FakeRenderer(tmp_path / "fallback.webp")

    with pytest.raises(ValueError, match="positive"):
        resolve_sticker_path(tmp_path, renderer, "flag", 0)


class FakeRepository:
    def __init__(self, resolved: str | None = None):
        self.resolved = resolved

    async def resolve_active_connection_id(self, connection_id: str):
        return self.resolved or connection_id


class FakeBot:
    def __init__(self):
        self.rich_kwargs = None
        self.text_kwargs = None

    async def send_rich_message(self, **kwargs):
        self.rich_kwargs = kwargs

    async def send_message(self, **kwargs):
        self.text_kwargs = kwargs


def test_status_uses_rich_h1_and_details(tmp_path):
    bot = FakeBot()
    service = StickerService(
        bot,
        FakeRepository(),
        FakeRenderer(tmp_path / "fallback.webp"),
        tmp_path,
    )

    asyncio.run(service.send_status(
        connection_id="bc-1",
        owner_user_id=10,
        chat_id=20,
        current=7,
        longest=12,
        completed_days=20,
        break_count=2,
        freeze_count=3,
        last_completed_day="2026-09-16",
    ))

    assert bot.rich_kwargs is not None
    rich = bot.rich_kwargs["rich_message"]
    assert rich.is_rtl is True
    assert "<h1>🔥 الستريك</h1>" in rich.html
    assert "<details><summary>التفاصيل</summary>" in rich.html
    assert "الحماية: <b>🧊🧊🧊</b>" in rich.html
    assert "آخر نجاح" in rich.html
    assert bot.text_kwargs is None
    assert '<tg-button type="disabled">⏳ ' in rich.html
    assert '<tg-button-row' not in rich.html
    assert 'format="r"' in rich.html
    assert 'قريبًا' not in rich.html



def test_zero_breaks_are_hidden_and_zero_protection_is_clear():
    rich = build_streak_rich_message(
        current=4,
        owner_user_id=10, chat_id=20,
        longest=9,
        completed_days=10,
        break_count=0,
        freeze_count=0,
        last_completed_day="2026-09-16",
        timezone_name="Asia/Baghdad",
    )

    assert rich.html is not None
    assert "عدد مرات انقطاع الستريك" not in rich.html
    assert "الحماية: <b>لا توجد</b>" in rich.html


def test_business_peer_invalid_is_not_retried_as_effect_failure(tmp_path):
    class RejectingBot:
        def __init__(self):
            self.calls = 0

        async def send_sticker(self, **kwargs):
            self.calls += 1
            raise TelegramBadRequest(
                method=object(),
                message="Bad Request: BUSINESS_PEER_INVALID",
            )

    async def scenario():
        bot = RejectingBot()
        service = StickerService(
            bot,
            FakeRepository(),
            FakeRenderer(tmp_path / "fallback.webp"),
            tmp_path,
            message_effect_id="effect",
        )
        with pytest.raises(TelegramBadRequest, match="BUSINESS_PEER_INVALID"):
            await service._send_sticker_once(
                connection_id="bc-1",
                chat_id=20,
                sticker="file-id",
                days=7,
                with_effect=True,
            )
        assert bot.calls == 1

    asyncio.run(scenario())


def test_status_uses_latest_resolved_business_connection(tmp_path):
    bot = FakeBot()
    service = StickerService(
        bot,
        FakeRepository("bc-new"),
        FakeRenderer(tmp_path / "fallback.webp"),
        tmp_path,
    )

    asyncio.run(service.send_status(
        connection_id="bc-old",
        owner_user_id=10,
        chat_id=20,
        current=7,
        longest=12,
        completed_days=20,
        break_count=0,
        freeze_count=3,
        last_completed_day="2026-09-16",
    ))

    assert bot.rich_kwargs["business_connection_id"] == "bc-new"
