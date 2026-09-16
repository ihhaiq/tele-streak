from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.stickers.poses import PoseCatalog

CANVAS_SIZE = 512
MIN_FONT_SIZE = 12


class StickerRenderer:
    """Fallback renderer for streak numbers without a committed ready sticker."""

    def __init__(self, catalog: PoseCatalog, rendered_dir: Path):
        self.catalog = catalog
        self.rendered_dir = rendered_dir
        self.rendered_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
        )
        for path in candidates:
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
        return ImageFont.load_default()

    def render(self, pose_id: str, days: int) -> Path:
        if days < 1:
            raise ValueError("days must be positive")

        pose = self.catalog.get(pose_id)
        stat = pose.image.stat()
        fingerprint = f"{stat.st_mtime_ns}:{stat.st_size}"
        digest = hashlib.sha1(
            f"{pose_id}:{days}:{fingerprint}:v3".encode()
        ).hexdigest()[:16]
        output = self.rendered_dir / f"streak_{days}_{pose_id}_{digest}.webp"
        if output.is_file():
            return output

        image = Image.open(pose.image).convert("RGBA")
        width, height = image.size
        left, top, right, bottom = pose.number_box
        box = (
            int(width * left),
            int(height * top),
            int(width * right),
            int(height * bottom),
        )
        text = str(days)
        if len(text) > pose.max_digits:
            raise ValueError(
                f"Pose {pose.id} supports at most {pose.max_digits} digits"
            )

        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        max_width = box[2] - box[0]
        max_height = box[3] - box[1]
        font_size = max(MIN_FONT_SIZE, pose.font_size)

        while font_size > MIN_FONT_SIZE:
            font = self._font(font_size)
            bounds = draw.textbbox(
                (0, 0),
                text,
                font=font,
                stroke_width=pose.outline_width,
            )
            if (
                bounds[2] - bounds[0] <= max_width
                and bounds[3] - bounds[1] <= max_height
            ):
                break
            font_size -= 2

        font = self._font(font_size)
        bounds = draw.textbbox(
            (0, 0),
            text,
            font=font,
            stroke_width=pose.outline_width,
        )
        x = box[0] + (max_width - (bounds[2] - bounds[0])) / 2 - bounds[0]
        y = box[1] + (max_height - (bounds[3] - bounds[1])) / 2 - bounds[1]
        draw.text(
            (x, y),
            text,
            font=font,
            fill=ImageColor.getcolor(pose.text_color, "RGBA"),
            stroke_width=pose.outline_width,
            stroke_fill=ImageColor.getcolor(pose.outline_color, "RGBA"),
        )

        if pose.rotation:
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            layer = layer.rotate(
                pose.rotation,
                resample=Image.Resampling.BICUBIC,
                center=center,
            )
        image.alpha_composite(layer)

        image.thumbnail((CANVAS_SIZE, CANVAS_SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new(
            "RGBA",
            (CANVAS_SIZE, CANVAS_SIZE),
            (255, 255, 255, 0),
        )
        position = (
            (CANVAS_SIZE - image.width) // 2,
            (CANVAS_SIZE - image.height) // 2,
        )
        canvas.alpha_composite(image, position)
        canvas.save(output, "WEBP", quality=92, method=6)
        return output
