from pathlib import Path

import pytest

from app.services.sticker_service import resolve_sticker_path


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
