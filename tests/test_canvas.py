from PIL import Image, ImageDraw

from app.stickers.canvas import CANVAS_SIZE, content_box, fit_to_canvas


def _art_with_thin_parts() -> Image.Image:
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((190, 170, 320, 350), fill=(255, 200, 0, 255))
    # Legitimate thin parts that must not be eroded/clipped.
    draw.rectangle((251, 145, 257, 175), fill=(255, 200, 0, 255))
    draw.rectangle((247, 348, 253, 385), fill=(255, 200, 0, 255))
    return image


def test_content_box_keeps_thin_top_and_bottom_artwork():
    source = _art_with_thin_parts()
    box = content_box(source)
    assert box[1] <= 145
    assert box[3] >= 386


def test_fit_to_canvas_is_large_but_keeps_safety_margin():
    fitted = fit_to_canvas(_art_with_thin_parts())
    assert fitted.size == (CANVAS_SIZE, CANVAS_SIZE)
    box = fitted.getbbox()
    longest = max(box[2] - box[0], box[3] - box[1])
    assert CANVAS_SIZE * 0.88 <= longest <= CANVAS_SIZE * 0.96


def test_fit_to_canvas_centers_visible_artwork():
    image = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((50, 120, 180, 300), fill=(0, 0, 255, 255))
    fitted = fit_to_canvas(image)
    left, top, right, bottom = fitted.getbbox()
    center_x = (left + right) / 2
    center_y = (top + bottom) / 2
    assert abs(center_x - CANVAS_SIZE / 2) <= 2
    assert abs(center_y - CANVAS_SIZE / 2) <= 2


def test_fit_to_canvas_keeps_aspect_ratio():
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((100, 150, 200, 200), fill=(0, 0, 255, 255))
    fitted = fit_to_canvas(image)
    box = fitted.getbbox()
    ratio = (box[2] - box[0]) / (box[3] - box[1])
    assert 1.8 < ratio < 2.2
