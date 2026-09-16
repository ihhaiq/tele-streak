from pathlib import Path

from PIL import Image

from app.services.sticker_pack import sticker_set_name
from app.stickers.pack_builder import ReadyPackBuilder

ROOT = Path(__file__).resolve().parents[1]
READY = ROOT / "assets" / "streak_stickers" / "jake" / "ready"
SPECIAL = ROOT / "assets" / "streak_stickers" / "jake" / "special"


def test_ready_sticker_pack_1_through_60_is_complete():
    expected = [f"{value:03}.webp" for value in range(1, 61)]
    actual = sorted(path.name for path in READY.glob("*.webp"))
    assert actual == expected


def test_ready_stickers_match_telegram_canvas():
    for path in READY.glob("*.webp"):
        with Image.open(path) as image:
            assert image.size == (512, 512)
            assert image.format == "WEBP"
        assert path.stat().st_size <= 512_000


def test_special_stickers_exist():
    assert (SPECIAL / "warning.webp").is_file()
    assert (SPECIAL / "broken.webp").is_file()


def test_sticker_set_name_is_deterministic():
    assert sticker_set_name("MyStreakBot") == "jake_streak_shared_1_by_mystreakbot"


def test_sticker_set_name_removes_invalid_characters():
    assert sticker_set_name("My-Streak.Bot") == "jake_streak_shared_1_by_mystreakbot"


def test_sticker_set_name_respects_telegram_limit():
    assert sticker_set_name("a" * 32, 3).endswith("_by_" + "a" * 32)


def test_pack_builder_creates_numbered_webp(tmp_path):
    sheet = Image.new("RGBA", (1374, 1145), (255, 220, 0, 255))
    sheet_path = tmp_path / "sheet.webp"
    sheet.save(sheet_path, "WEBP")
    ready = tmp_path / "ready"

    ReadyPackBuilder(sheet_path, ready).ensure(61, 62)

    for day in (61, 62):
        path = ready / f"{day:03}.webp"
        assert path.is_file()
        with Image.open(path) as sticker:
            assert sticker.size == (512, 512)
            assert sticker.format == "WEBP"


def test_ready_stickers_fill_the_canvas():
    """Artwork must reach the canvas edges; Telegram renders stickers as-is."""
    for path in READY.glob("*.webp"):
        with Image.open(path) as image:
            box = image.convert("RGBA").getbbox()
        longest = max(box[2] - box[0], box[3] - box[1])
        assert longest >= 450, f"{path.name} only fills {longest}px of 512"
