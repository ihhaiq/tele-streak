from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class StickerRenderer:
    def __init__(self, assets_dir: Path, rendered_dir: Path):
        self.assets_dir = assets_dir
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
                pass
        return ImageFont.load_default()

    def render(self, pose_name: str, days: int) -> Path:
        key = hashlib.sha1(f"{pose_name}:{days}:v2".encode()).hexdigest()[:16]
        output = self.rendered_dir / f"streak_{days}_{key}.webp"
        if output.exists():
            return output

        source = self.assets_dir / pose_name
        image = Image.open(source).convert("RGBA")

        # The test art has Jake holding a flag. Replace only the flag number.
        # Coordinates are relative, so the asset can be resized/re-exported later.
        draw = ImageDraw.Draw(image)
        w, h = image.size
        box = (
            int(w * 0.19),
            int(h * 0.075),
            int(w * 0.76),
            int(h * 0.285),
        )
        draw.rounded_rectangle(box, radius=max(4, int(w * 0.025)), fill=(255, 248, 232, 255))

        text = str(days)
        max_width = box[2] - box[0] - 10
        max_height = box[3] - box[1] - 6
        size = max(18, int(h * 0.17))
        while size > 18:
            font = self._font(size)
            bounds = draw.textbbox((0, 0), text, font=font, stroke_width=0)
            tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
            if tw <= max_width and th <= max_height:
                break
            size -= 2
        font = self._font(size)
        bounds = draw.textbbox((0, 0), text, font=font)
        tw, th = bounds[2] - bounds[0], bounds[3] - bounds[1]
        x = box[0] + ((box[2] - box[0]) - tw) / 2
        y = box[1] + ((box[3] - box[1]) - th) / 2 - bounds[1]
        draw.text((x, y), text, font=font, fill=(23, 43, 58, 255))

        # Telegram static stickers: one side exactly 512 px, both sides <=512.
        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
        x = (512 - image.width) // 2
        y = (512 - image.height) // 2
        canvas.alpha_composite(image, (x, y))
        canvas.save(output, "WEBP", quality=95, method=6)
        return output
