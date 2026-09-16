from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.stickers.canvas import fit_to_canvas

CELL = 229
COLS = 6
ROWS = 5
CANVAS = 512

# Number centers inside each generated sprite cell. Values are normalized.
NUMBER_CENTERS = (
    (0.43, 0.57), (0.50, 0.66), (0.50, 0.65), (0.50, 0.73),
    (0.50, 0.46), (0.66, 0.29), (0.43, 0.70), (0.51, 0.67),
    (0.65, 0.54), (0.28, 0.72), (0.50, 0.84), (0.60, 0.80),
    (0.43, 0.81), (0.30, 0.80), (0.50, 0.72), (0.50, 0.84),
    (0.53, 0.70), (0.66, 0.84), (0.49, 0.73), (0.57, 0.79),
    (0.50, 0.65), (0.50, 0.64), (0.50, 0.70), (0.50, 0.76),
    (0.63, 0.54), (0.43, 0.61), (0.50, 0.73), (0.50, 0.79),
    (0.61, 0.54), (0.68, 0.35),
)


@lru_cache(maxsize=8)
def _font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


class ReadyPackBuilder:
    """Build missing numbered WebP assets once from the reviewed pose sheet."""

    def __init__(self, sheet_path: Path, ready_dir: Path) -> None:
        self.sheet_path = sheet_path
        self.ready_dir = ready_dir

    def ensure(self, start: int = 61, end: int = 250) -> None:
        self.ready_dir.mkdir(parents=True, exist_ok=True)
        missing = [
            day for day in range(start, end + 1)
            if not (self.ready_dir / f"{day:03}.webp").is_file()
        ]
        if not missing:
            return
        if not self.sheet_path.is_file():
            raise FileNotFoundError(self.sheet_path)

        sheet = Image.open(self.sheet_path).convert("RGBA")
        if sheet.size != (CELL * COLS, CELL * ROWS):
            sheet = sheet.resize((CELL * COLS, CELL * ROWS), Image.Resampling.LANCZOS)

        for day in missing:
            pose_index = (day - 61) % (COLS * ROWS)
            col, row = pose_index % COLS, pose_index // COLS
            pose = sheet.crop((col * CELL, row * CELL, (col + 1) * CELL, (row + 1) * CELL))
            pose = pose.resize((CANVAS, CANVAS), Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(pose)
            text = str(day)
            size = 112 if len(text) <= 2 else 86
            font = _font(size)
            bounds = draw.textbbox((0, 0), text, font=font, stroke_width=6)
            width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
            cx, cy = NUMBER_CENTERS[pose_index]
            x = CANVAS * cx - width / 2 - bounds[0]
            y = CANVAS * cy - height / 2 - bounds[1]
            draw.text(
                (x, y), text, font=font, fill="#FFFFFF",
                stroke_width=6, stroke_fill="#171717",
            )
            fit_to_canvas(pose).save(
                self.ready_dir / f"{day:03}.webp",
                "WEBP", quality=88, method=4,
            )
