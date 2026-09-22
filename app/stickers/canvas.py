from __future__ import annotations

from PIL import Image, ImageFilter

CANVAS_SIZE = 512
# Keep a small, consistent safety area while letting the artwork fill more of
# Telegram's 512px sticker canvas.
MARGIN_RATIO = 0.03
ALPHA_FLOOR = 18
# A very light close joins tiny gaps in outlines without eroding real artwork.
CLOSE_WINDOW = 3
# Expand the detected artwork before resizing so antialiased edges survive.
CONTENT_PADDING = 6


def content_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Return conservative bounds around visible artwork.

    Older code eroded the alpha mask to remove sprite-sheet bleed. That could
    also erase legitimate thin parts (ears, feet, tails) and make some stickers
    look clipped. We now threshold softly, close tiny gaps, and grow the box.
    """
    image = image.convert("RGBA")
    width, height = image.size
    alpha = image.getchannel("A")
    mask = alpha.point(lambda value: 255 if value > ALPHA_FLOOR else 0)
    mask = mask.filter(ImageFilter.MaxFilter(CLOSE_WINDOW)).filter(
        ImageFilter.MinFilter(CLOSE_WINDOW)
    )
    box = mask.getbbox()
    if box is None:
        return (0, 0, width, height)

    left, top, right, bottom = box
    return (
        max(0, left - CONTENT_PADDING),
        max(0, top - CONTENT_PADDING),
        min(width, right + CONTENT_PADDING),
        min(height, bottom + CONTENT_PADDING),
    )


def fit_to_canvas(
    image: Image.Image,
    *,
    size: int = CANVAS_SIZE,
    margin_ratio: float = MARGIN_RATIO,
    sharpen: bool = True,
) -> Image.Image:
    """Crop transparent whitespace, scale safely, and center the artwork."""
    image = image.convert("RGBA")
    cropped = image.crop(content_box(image))
    if cropped.width <= 0 or cropped.height <= 0:
        cropped = image

    target = max(1, int(round(size * (1 - 2 * margin_ratio))))
    scale = min(target / cropped.width, target / cropped.height)
    new_size = (
        max(1, int(round(cropped.width * scale))),
        max(1, int(round(cropped.height * scale))),
    )
    resized = cropped.resize(new_size, Image.Resampling.LANCZOS)
    if sharpen and scale > 1.05:
        resized = resized.filter(
            ImageFilter.UnsharpMask(radius=1.3, percent=55, threshold=2)
        )

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - resized.width) // 2
    y = (size - resized.height) // 2
    canvas.alpha_composite(resized, (x, y))
    return canvas
