from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
READY = ROOT / "assets" / "streak_stickers" / "jake" / "ready"
SPECIAL = ROOT / "assets" / "streak_stickers" / "jake" / "special"


def test_ready_sticker_pack_1_through_50_is_complete():
    expected = [f"{value:03}.webp" for value in range(1, 51)]
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
