"""Rescale committed WEBP stickers so the artwork fills the 512x512 canvas.

Run once after adding or replacing reviewed art:

    python -m tools.upscale_stickers          # rewrite assets in place
    python -m tools.upscale_stickers --check  # report only, no writes
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from app.stickers.canvas import CANVAS_SIZE, fit_to_canvas

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (
    ROOT / "assets" / "streak_stickers" / "jake" / "ready",
    ROOT / "assets" / "streak_stickers" / "jake" / "special",
)
# Telegram rejects static stickers above 512 KB.
MAX_BYTES = 512 * 1024


MIN_COMPONENT_SHARE = 0.03
MAX_COMPONENT_GAP = 30
# Seam bleed is always a narrow strip; real extras (a zZz, a crown) are not.
MIN_COMPONENT_THICKNESS = 26


def drop_detached_parts(image: Image.Image) -> Image.Image:
    """Remove art fragments that bled in from neighbouring sprite-sheet cells.

    Keeps the main silhouette plus anything close enough to belong to it (a
    speech bubble, a `zZz`), and deletes blobs floating far away.
    """
    try:
        import numpy as np
        from scipy import ndimage
    except ImportError:
        print("numpy/scipy missing; skipping detached-part cleanup")
        return image

    alpha = np.array(image.getchannel("A"))
    mask = alpha > 32
    labels, count = ndimage.label(mask)
    if count <= 1:
        return image

    boxes = ndimage.find_objects(labels)
    sizes = [int(mask[box].sum()) for box in boxes]
    main = int(np.argmax(sizes))
    main_rows, main_cols = boxes[main]

    keep = np.zeros_like(mask)
    for index, (rows, cols) in enumerate(boxes):
        if index != main:
            if sizes[index] < sizes[main] * MIN_COMPONENT_SHARE:
                continue
            thickness = min(rows.stop - rows.start, cols.stop - cols.start)
            if thickness <= MIN_COMPONENT_THICKNESS:
                continue
            row_gap = max(main_rows.start - rows.stop, rows.start - main_rows.stop, 0)
            col_gap = max(main_cols.start - cols.stop, cols.start - main_cols.stop, 0)
            if max(row_gap, col_gap) > MAX_COMPONENT_GAP:
                continue
        keep |= labels == index + 1

    cleaned = image.copy()
    cleaned.putalpha(Image.fromarray((alpha * keep).astype("uint8")))
    return cleaned


def occupancy(image: Image.Image) -> float:
    box = image.getbbox()
    if not box:
        return 0.0
    return max(box[2] - box[0], box[3] - box[1]) / max(image.size)


def save_webp(image: Image.Image, path: Path) -> int:
    for quality in (92, 88, 82, 75):
        image.save(path, "WEBP", quality=quality, method=6)
        if path.stat().st_size <= MAX_BYTES:
            break
    return path.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="report only")
    parser.add_argument("--min-occupancy", type=float, default=0.90)
    args = parser.parse_args()

    changed = 0
    for directory in TARGETS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.webp")):
            with Image.open(path) as source:
                image = source.convert("RGBA")
            before = occupancy(image)
            if before >= args.min_occupancy and image.size == (CANVAS_SIZE, CANVAS_SIZE):
                continue
            changed += 1
            if args.check:
                print(f"{path.name}: fills {before:.0%} of the canvas")
                continue
            fitted = fit_to_canvas(drop_detached_parts(image))
            size = save_webp(fitted, path)
            print(f"{path.name}: {before:.0%} -> {occupancy(fitted):.0%} ({size // 1024} KB)")

    print(f"{'would rewrite' if args.check else 'rewrote'} {changed} sticker(s)")


if __name__ == "__main__":
    main()
