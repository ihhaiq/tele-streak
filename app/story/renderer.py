from __future__ import annotations

import math
import random
import shutil
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from app.stickers.canvas import fit_to_canvas

WIDTH, HEIGHT, FPS = 720, 1280, 24
ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=64)
def font(size):
    return ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
    )


def clean_name(name: str) -> str:
    return (
        "".join(c for c in name if not unicodedata.category(c).startswith("C")).strip()[
            :40
        ]
        or "صديق"
    )


def centered(draw, text, y, size, fill, width=640):
    text = clean_name(text)
    while size > 14 and draw.textlength(text, font=font(size)) > width:
        size -= 1
    draw.text(
        (WIDTH // 2, y),
        text,
        font=font(size),
        anchor="mm",
        fill=fill,
        direction="rtl" if any("\u0600" <= c <= "\u06ff" for c in text) else "ltr",
    )


def celebration_art(size=512) -> Image.Image:
    # الوضعية الخام مفرحة وما بيها رقم أصلًا.
    with Image.open(ROOT / "assets/jake/generated/poses_sheet.webp") as source:
        sheet = source.convert("RGBA")
    # حدود هذه الوضعية مو مساوية لشبكة الملصقات القديمة.
    pose = sheet.crop((440, 488, 692, 738))
    mask = pose.getchannel("A").point(lambda value: 255 if value > 24 else 0)
    ImageDraw.floodfill(mask, (126, 150), 128, thresh=0)
    connected = mask.point(lambda value: 255 if value == 128 else 0)
    connected = connected.filter(ImageFilter.MaxFilter(3))
    pose.putalpha(ImageChops.multiply(pose.getchannel("A"), connected))
    return fit_to_canvas(pose, size=size)


def write_celebration(path: Path) -> Path:
    celebration_art().save(path, "WEBP", quality=92)
    return path


def avatar_ball(name: str, image_path: Path | None, color: str) -> Image.Image:
    size = 192
    ball = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(ball)
    draw.ellipse((1, 1, size - 2, size - 2), fill=color, outline="white", width=5)
    if image_path and image_path.is_file():
        try:
            with Image.open(image_path) as source:
                photo = ImageOps.fit(source.convert("RGB"), (146, 146))
            mask = Image.new("L", (146, 146))
            ImageDraw.Draw(mask).ellipse((0, 0, 145, 145), fill=255)
            ball.paste(photo, (23, 10), mask)
        except (OSError, ValueError):
            image_path = None
    if not image_path:
        draw.text(
            (96, 67), clean_name(name)[0], font=font(65), anchor="mm", fill="white"
        )
    name = clean_name(name)
    while draw.textlength(name, font=font(19)) > 151 and len(name) > 2:
        name = name[:-2] + "…"
    draw.rounded_rectangle((17, 137, 175, 173), radius=16, fill="#142342")
    draw.text(
        (96, 154),
        name,
        font=font(19),
        anchor="mm",
        fill="white",
        direction="rtl" if any("\u0600" <= c <= "\u06ff" for c in name) else "ltr",
    )
    return ball


def story_card(
    *,
    days: int,
    names: tuple[str, str],
    photos: tuple[Path | None, Path | None] = (None, None),
) -> Image.Image:
    """Build the still 9:16 story requested by the product flow."""
    if days < 1:
        raise ValueError("Story requires a positive streak")

    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    palette = ("#ffd56b", "#7ce3d2", "#e4a9ff", "#ff969f")

    for y in range(HEIGHT):
        draw.line(
            (0, y, WIDTH, y),
            fill=(
                19 + y * 7 // HEIGHT,
                25 + y * 8 // HEIGHT,
                57 + y * 17 // HEIGHT,
            ),
        )

    draw.rounded_rectangle((210, 92, 510, 141), radius=24, fill="#303b66")
    centered(draw, "JAKE & FRIENDS", 116, 19, "#ffe8a6")
    centered(draw, "ستريك متتالي", 213, 48, "white")
    centered(draw, f"لـ {days} يوم", 286, 68, "#ffd56b")

    rng = random.Random(84 + days)
    for _ in range(72):
        x = rng.randrange(35, WIDTH - 35)
        y = rng.randrange(360, 1110)
        color = rng.choice(palette)
        if 500 < y < 990 and 150 < x < 570:
            continue
        draw.rounded_rectangle((x, y, x + 6, y + 13), radius=2, fill=color)

    canvas = image.convert("RGBA")
    jake = celebration_art(460)
    canvas.alpha_composite(jake, (WIDTH // 2 - 230, 595))

    balls = [
        avatar_ball(name, photo, palette[index])
        for index, (name, photo) in enumerate(zip(names, photos))
    ]
    positions = ((72, 445), (456, 445))
    for ball, position in zip(balls, positions):
        canvas.alpha_composite(ball, position)

    # خطوط الحركة تخلي الكرتين يبينن كأن Jake دا يلعب بيهن.
    motion = ImageDraw.Draw(canvas)
    motion.arc((95, 382, 625, 720), start=202, end=338, fill=(255, 255, 255, 136), width=5)
    motion.arc((127, 414, 593, 690), start=205, end=335, fill=(255, 213, 107, 136), width=3)

    footer = ImageDraw.Draw(canvas)
    footer.rounded_rectangle((92, 1080, 628, 1165), radius=34, fill="#142342")
    centered(footer, "كل يوم، أقرب 🤝", 1121, 30, "white")
    centered(footer, "STREAK TOGETHER", 1208, 16, "#919aba")
    return canvas.convert("RGB")


class StoryRenderer:
    def render_image(
        self,
        directory: Path,
        *,
        days: int,
        names: tuple[str, str],
        photos: tuple[Path | None, Path | None] = (None, None),
    ) -> Path:
        if not features.check_feature("raqm"):
            raise RuntimeError("Pillow must support RAQM for Arabic text")
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / "streak-story.jpg"
        card = story_card(days=days, names=names, photos=photos)
        card.resize((1080, 1920), Image.Resampling.LANCZOS).save(
            output,
            "JPEG",
            quality=92,
            optimize=True,
            progressive=True,
        )
        return output

    def render(
        self,
        directory: Path,
        *,
        days: int,
        names: tuple[str, str],
        photos: tuple[Path | None, Path | None] = (None, None),
        duration: int = 5,
        music_path: Path | None = None,
    ) -> Path:
        if duration not in (5, 10) or days < 1:
            raise ValueError("Story requires a positive streak and 5 or 10 seconds")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("FFmpeg is required")
        if not features.check_feature("raqm"):
            raise RuntimeError("Pillow must support RAQM for Arabic text")
        directory.mkdir(parents=True, exist_ok=True)
        frames = directory / "frames"
        frames.mkdir()
        music = music_path if music_path and music_path.is_file() else None
        background = Image.new("RGB", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(background)
        palette = ("#ffd56b", "#7ce3d2", "#e4a9ff", "#ff969f")
        for y in range(HEIGHT):
            draw.line(
                (0, y, WIDTH, y),
                fill=(
                    19 + y * 7 // HEIGHT,
                    25 + y * 8 // HEIGHT,
                    57 + y * 17 // HEIGHT,
                ),
            )
        draw.rounded_rectangle((210, 113, 510, 162), radius=24, fill="#303b66")
        centered(draw, "JAKE & FRIENDS", 137, 19, "#ffe8a6")
        centered(draw, "ستريك متتالي", 224, 46, "white")
        centered(draw, f"لـ {days} يوم", 296, 66, "#ffd56b")
        centered(draw, "كل يوم، أقرب", 1130, 29, "#e1e4fa")
        centered(draw, "STREAK TOGETHER", 1184, 15, "#919aba")
        balls = [
            avatar_ball(n, p, palette[i]) for i, (n, p) in enumerate(zip(names, photos))
        ]
        jake = celebration_art(420)
        rng = random.Random(84)
        confetti = [
            (
                rng.randrange(WIDTH),
                rng.randrange(HEIGHT),
                rng.choice(palette),
                rng.uniform(30, 75),
            )
            for _ in range(48)
        ]
        for frame in range(duration * FPS):
            t = frame / FPS
            image = background.copy().convert("RGBA")
            draw = ImageDraw.Draw(image)
            for x, y, color, speed in confetti:
                yy = (y + t * speed) % HEIGHT
                if 370 < yy < 1070:
                    draw.rounded_rectangle(
                        (x, yy, x + 5, yy + 11), radius=2, fill=color
                    )
            beat = math.sin(2 * math.pi * t)
            draw.ellipse((225, 982, 495, 1014), fill="#14192f")
            actor = jake.resize(
                (420 + int(8 * beat), 420 - int(12 * beat)), Image.Resampling.BICUBIC
            )
            actor = actor.rotate(
                5 * math.sin(math.pi * t), Image.Resampling.BICUBIC, expand=True
            )
            image.alpha_composite(
                actor,
                (360 - actor.width // 2, 795 - actor.height // 2 - int(15 * abs(beat))),
            )
            for i, ball in enumerate(balls):
                phase = (t / 2 + i * 0.5) % 1
                # رمية لكل يد، بمسار ناعم يرجع لنفس موضعه.
                x = 190 + 340 * i + 35 * math.sin(2 * math.pi * phase)
                y = 685 - 210 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
                tilt = ball.rotate(
                    9 * math.sin(2 * math.pi * phase),
                    Image.Resampling.BICUBIC,
                    expand=True,
                )
                image.alpha_composite(
                    tilt, (round(x - tilt.width / 2), round(y - tilt.height / 2))
                )
            image.convert("RGB").save(frames / f"{frame:04}.jpg", quality=92)
        output = directory / "streak-story.mp4"
        command = [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(FPS),
                "-i",
                str(frames / "%04d.jpg"),
                *(["-i", str(music)] if music else []),
                "-t",
                str(duration),
                "-map",
                "0:v:0",
                *(["-map", "1:a:0"] if music else []),
                "-c:v",
                "libx265",
                "-preset",
                "fast",
                "-threads",
                "2",
                "-crf",
                "27",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(FPS),
                "-keyint_min",
                str(FPS),
                "-sc_threshold",
                "0",
                "-tag:v",
                "hvc1",
                "-movflags",
                "+faststart",
        ]
        if music:
            command += [
                "-c:a", "aac", "-b:a", "128k", "-af",
                f"afade=t=in:st=0:d=0.2,afade=t=out:st={duration - 0.4}:d=0.4",
            ]
        command += [str(output)]
        subprocess.run(
            command,
            check=True,
            timeout=90,
            capture_output=True,
        )
        return output
