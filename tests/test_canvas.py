from PIL import Image, ImageDraw

from app.stickers.canvas import CANVAS_SIZE, content_box, fit_to_canvas


def _art_with_bleed() -> Image.Image:
    image = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((200, 200, 300, 320), fill=(255, 200, 0, 255))
    # 3px sliver bleeding in from a neighbouring sprite-sheet cell
    draw.rectangle((470, 150, 472, 380), fill=(255, 0, 0, 255))
    return image


def test_content_box_ignores_thin_bleed():
    box = content_box(_art_with_bleed())
    assert box[2] < 400


def test_fit_to_canvas_fills_the_frame():
    fitted = fit_to_canvas(_art_with_bleed())
    assert fitted.size == (CANVAS_SIZE, CANVAS_SIZE)
    box = fitted.getbbox()
    assert max(box[2] - box[0], box[3] - box[1]) >= CANVAS_SIZE * 0.9


def test_fit_to_canvas_keeps_aspect_ratio():
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((100, 150, 200, 200), fill=(0, 0, 255, 255))
    fitted = fit_to_canvas(image)
    box = fitted.getbbox()
    ratio = (box[2] - box[0]) / (box[3] - box[1])
    assert 1.8 < ratio < 2.2
