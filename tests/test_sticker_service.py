import asyncio
from pathlib import Path

import pytest

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
        object(),
        FakeRenderer(tmp_path / "fallback.webp"),
        tmp_path,
    )

    asyncio.run(service.send_status(
        connection_id="bc-1",
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
    assert "<h1>🔥 حالة الستريك</h1>" in rich.html
    assert "<details><summary>تفاصيل الستريك 🫠</summary>" in rich.html
    assert "رصيد الحماية: <b>3 🧊</b>" in rich.html
    assert "آخر يوم تم احتسابه ضمن الستريك" in rich.html
    assert bot.text_kwargs is None
