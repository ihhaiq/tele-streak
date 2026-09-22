import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image

from app.services.sticker_pack import StickerPack, sticker_set_name
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
    assert sticker_set_name("MyStreakBot") == "jake_streak_shared_v3_1_by_mystreakbot"


def test_sticker_set_name_removes_invalid_characters():
    assert sticker_set_name("My-Streak.Bot") == "jake_streak_shared_v3_1_by_mystreakbot"


def test_sticker_set_name_respects_telegram_limit():
    assert sticker_set_name("a" * 32, 3).endswith("_by_" + "a" * 32)


def test_pack_builder_force_rebuild_replaces_damaged_ready_asset(tmp_path):
    sheet = Image.new("RGBA", (1374, 1145), (255, 220, 0, 255))
    sheet_path = tmp_path / "sheet.webp"
    sheet.save(sheet_path, "WEBP")
    ready = tmp_path / "ready"
    ready.mkdir()
    damaged = ready / "017.webp"
    Image.new("RGBA", (512, 512), (255, 0, 0, 255)).save(damaged, "WEBP")
    before = damaged.read_bytes()

    ReadyPackBuilder(sheet_path, ready).ensure(17, 17, force=True)

    assert damaged.read_bytes() != before
    with Image.open(damaged) as sticker:
        assert sticker.size == (512, 512)
        assert sticker.format == "WEBP"


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


def test_ready_stickers_have_visible_artwork():
    """Committed sources may vary; upload normalization handles final sizing."""
    for path in READY.glob("*.webp"):
        with Image.open(path) as image:
            box = image.convert("RGBA").getbbox()
        assert box is not None, f"{path.name} has no visible artwork"


def test_refresh_numbered_file_id_reads_only_target_pack(tmp_path):
    stickers = [
        SimpleNamespace(file_id=f"file-{index}")
        for index in range(1, 121)
    ]
    bot = SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="HStreakBot")),
        get_sticker_set=AsyncMock(
            return_value=SimpleNamespace(stickers=stickers)
        ),
    )
    pack = StickerPack(bot, tmp_path / "ready", owner_id=1)

    file_id = asyncio.run(pack.refresh_numbered_file_id(121))

    assert file_id == "file-1"
    bot.get_sticker_set.assert_awaited_once_with(
        sticker_set_name("HStreakBot", 2)
    )
    assert pack.cached_file_id("121") == "file-1"
