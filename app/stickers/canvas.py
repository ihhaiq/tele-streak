from __future__ import annotations

from PIL import Image, ImageFilter

CANVAS_SIZE = 512
# Telegram renders stickers edge to edge; a small margin keeps outlines intact.
MARGIN_RATIO = 0.02
# Pixels under this alpha are treated as empty.
ALPHA_FLOOR = 32
# Erosion window; slivers thinner than this are sprite-sheet bleed, not art.
ERODE_WINDOW = 5
# How far the box is grown back after erosion, to restore soft outlines.
BLEED_PADDING = 4


def content_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the real artwork, ignoring thin stray pixels.

    Eroding the alpha mask before measuring removes the 1-3px slivers that
    bleed in from neighbouring sprite-sheet cells, which would otherwise drag
    ``Image.getbbox`` to the edge of the frame and shrink the visible art.
    """
    width, height = image.size
    raw_box = image.getbbox() or (0, 0, width, height)

    mask = image.getchannel("A").point(
        lambda value: 255 if value > ALPHA_FLOOR else 0
    )
    eroded = mask.filter(ImageFilter.MinFilter(ERODE_WINDOW))
    box = eroded.getbbox()
    if box is None:
        return raw_box

    left, top, right, bottom = box
    return (
        max(raw_box[0], left - BLEED_PADDING),
        max(raw_box[1], top - BLEED_PADDING),
        min(raw_box[2], right + BLEED_PADDING),
        min(raw_box[3], bottom + BLEED_PADDING),
    )


def clean_strays(image: Image.Image) -> Image.Image:
    """Erase thin leftover pixels while keeping the artwork's soft outline."""
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > ALPHA_FLOOR else 0)
    keep = mask.filter(ImageFilter.MinFilter(ERODE_WINDOW)).filter(
        ImageFilter.MaxFilter(ERODE_WINDOW + 2 * BLEED_PADDING)
    )
    if not keep.getbbox():
        return image
    cleaned = image.copy()
    cleaned.putalpha(
        Image.composite(alpha, Image.new("L", alpha.size, 0), keep)
    )
    return cleaned


def fit_to_canvas(
    image: Image.Image,
    *,
    size: int = CANVAS_SIZE,
    margin_ratio: float = MARGIN_RATIO,
    sharpen: bool = True,
) -> Image.Image:
    """Crop to the artwork and scale it to fill a transparent square canvas."""
    image = clean_strays(image.convert("RGBA"))
    box = content_box(image)
    cropped = image.crop(box)
    if cropped.width == 0 or cropped.height == 0:
        cropped = image

    target = max(1, int(round(size * (1 - 2 * margin_ratio))))
    scale = target / max(cropped.width, cropped.height)
    new_size = (
        max(1, int(round(cropped.width * scale))),
        max(1, int(round(cropped.height * scale))),
    )
    resized = cropped.resize(new_size, Image.Resampling.LANCZOS)
    if sharpen and scale > 1.05:
        resized = resized.filter(
            ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2)
        )

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return canvas
