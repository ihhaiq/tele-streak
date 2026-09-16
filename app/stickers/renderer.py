from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from app.stickers.poses import PoseCatalog


class StickerRenderer:
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
                pass
        return ImageFont.load_default()

    def prewarm(self, through_day: int = 250) -> int:
        """Generate the reusable local sticker pack once; existing files are cache hits."""
        manifest_path = self.rendered_dir / "pack_1_250.json"
        manifest: dict[str, str] = {}
        last_pose: str | None = None
        for days in range(1, through_day + 1):
            pose = self.catalog.choose(days, last_pose)
            self.render(pose.id, days)
            manifest[str(days)] = pose.id
            last_pose = pose.id
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(manifest)

    def render(self, pose_id: str, days: int) -> Path:
        pose = self.catalog.get(pose_id)
        source_fingerprint = f"{pose.image.stat().st_mtime_ns}:{pose.image.stat().st_size}"
        key = hashlib.sha1(f"{pose_id}:{days}:{source_fingerprint}:v3".encode()).hexdigest()[:16]
        output = self.rendered_dir / f"streak_{days}_{pose_id}_{key}.webp"
        if output.exists():
            return output

        image = Image.open(pose.image).convert("RGBA")
        w, h = image.size
        left, top, right, bottom = pose.number_box
        box = (int(w * left), int(h * top), int(w * right), int(h * bottom))
        text = str(days)
        if len(text) > pose.max_digits:
            raise ValueError(f"Pose {pose.id} supports at most {pose.max_digits} digits")

        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        max_width = box[2] - box[0]
        max_height = box[3] - box[1]
        size = max(12, pose.font_size)
        while size > 12:
            font = self._font(size)
            bounds = draw.textbbox((0, 0), text, font=font, stroke_width=pose.outline_width)
            if bounds[2] - bounds[0] <= max_width and bounds[3] - bounds[1] <= max_height:
                break
            size -= 2

        font = self._font(size)
        bounds = draw.textbbox((0, 0), text, font=font, stroke_width=pose.outline_width)
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
            layer = layer.rotate(pose.rotation, resample=Image.Resampling.BICUBIC, center=((box[0]+box[2])/2, (box[1]+box[3])/2))
        image.alpha_composite(layer)

        image.thumbnail((512, 512), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (512, 512), (255, 255, 255, 0))
        canvas.alpha_composite(image, ((512 - image.width) // 2, (512 - image.height) // 2))
        canvas.save(output, "WEBP", quality=92, method=6)
        return output
