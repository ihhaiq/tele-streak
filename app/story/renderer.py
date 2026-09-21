from __future__ import annotations

import math
import random
import shutil
import subprocess
import unicodedata
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageFont, ImageOps, features

from app.stickers.canvas import fit_to_canvas
from app.story.motion_v2 import (
    FPS,
    JakeRig,
    ball_shadow,
    confetti_particles,
    confetti_state,
    motion_blur_samples,
    motion_layout,
    timeline_state,
)

WIDTH, HEIGHT = 720, 1280
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




def _animated_centered(
    image: Image.Image,
    text: str,
    *,
    y: int,
    size: int,
    fill: str,
    alpha: float,
    scale: float,
    width: int = 640,
) -> None:
    if alpha <= 0.01:
        return
    text = clean_name(text)
    font_size = size
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    while font_size > 14 and probe.textlength(text, font=font(font_size)) > width:
        font_size -= 1

    sprite_height = max(96, font_size * 3)
    sprite = Image.new("RGBA", (WIDTH, sprite_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    draw.text(
        (WIDTH // 2, sprite_height // 2),
        text,
        font=font(font_size),
        anchor="mm",
        fill=fill,
        direction="rtl" if any("\u0600" <= c <= "\u06ff" for c in text) else "ltr",
    )
    bbox = sprite.getbbox()
    if bbox is None:
        return
    sprite = sprite.crop(bbox)

    if abs(scale - 1.0) > 0.002:
        sprite = sprite.resize(
            (
                max(1, round(sprite.width * scale)),
                max(1, round(sprite.height * scale)),
            ),
            Image.Resampling.LANCZOS,
        )

    if alpha < 0.999:
        mask = sprite.getchannel("A").point(
            lambda value: round(value * max(0.0, min(1.0, alpha)))
        )
        sprite.putalpha(mask)

    image.alpha_composite(
        sprite,
        (
            WIDTH // 2 - sprite.width // 2,
            round(y - sprite.height / 2),
        ),
    )


def _draw_ball(
    image: Image.Image,
    ball: Image.Image,
    motion,
    *,
    alpha: int = 255,
) -> None:
    width = max(1, round(ball.width * motion.scale_x))
    height = max(1, round(ball.height * motion.scale_y))
    sprite = ball.resize((width, height), Image.Resampling.LANCZOS)
    if alpha < 255:
        sprite = sprite.copy()
        sprite.putalpha(
            sprite.getchannel("A").point(
                lambda value: round(value * alpha / 255)
            )
        )
    x, y = motion.center
    image.alpha_composite(
        sprite,
        (
            round(x - sprite.width / 2),
            round(y - sprite.height / 2),
        ),
    )


def _draw_ball_with_blur(
    image: Image.Image,
    ball: Image.Image,
    *,
    t: float,
    index: int,
    days: int,
    duration: int,
    motion,
) -> None:
    for sample, alpha in reversed(
        motion_blur_samples(
            t,
            index,
            days=days,
            duration=duration,
        )
    ):
        _draw_ball(image, ball, sample, alpha=alpha)
    _draw_ball(image, ball, motion)



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

    footer = ImageDraw.Draw(canvas)
    footer.rounded_rectangle((92, 1015, 628, 1095), radius=34, fill="#142342")
    centered(footer, "كل يوم، أقرب 🤝", 1055, 30, "white")
    centered(footer, "STREAK TOGETHER", 1125, 16, "#919aba")
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
        draw.rounded_rectangle((210, 90, 510, 139), radius=24, fill="#303b66")
        centered(draw, "JAKE & FRIENDS", 114, 19, "#ffe8a6")
        balls = [
            avatar_ball(n, p, palette[i]) for i, (n, p) in enumerate(zip(names, photos))
        ]
        jake_source = celebration_art(420)
        rig = JakeRig(jake_source, celebration=True)
        confetti = confetti_particles(days, duration)
        for frame in range(duration * FPS):
            t = frame / FPS
            timeline = timeline_state(t, duration=duration, days=days)
            layout = motion_layout(t, duration=duration, days=days)
            image = background.copy().convert("RGBA")
            draw = ImageDraw.Draw(image)

            # Confetti صار bursts لها بداية ونهاية وجاذبية بدل مطر مستمر.
            for particle in confetti:
                state = confetti_state(particle, t)
                if state is None:
                    continue
                x, y, rotation, alpha = state
                if not (-20 <= x <= WIDTH + 20 and -20 <= y <= HEIGHT + 20):
                    continue
                radians = math.radians(rotation)
                half = particle.size * 0.75
                dx = math.cos(radians) * half
                dy = math.sin(radians) * half
                color = palette[particle.color_index]
                rgb = ImageColor.getrgb(color)
                draw.line(
                    (x - dx, y - dy, x + dx, y + dy),
                    fill=(*rgb, alpha),
                    width=max(2, round(particle.size * 0.55)),
                )

            # ظل كل كرة يتغير مع ارتفاعها.
            for motion in layout.balls:
                sx, sy, sw, sa = ball_shadow(motion)
                draw.ellipse(
                    (
                        sx - sw / 2,
                        sy - sw * 0.14,
                        sx + sw / 2,
                        sy + sw * 0.14,
                    ),
                    fill=(10, 13, 28, sa),
                )

            # الكرة اللي تمر خلف Jake تنرسم أولًا مع motion blur.
            for index, (ball, motion) in enumerate(zip(balls, layout.balls)):
                if not motion.front:
                    _draw_ball_with_blur(
                        image,
                        ball,
                        t=t,
                        index=index,
                        days=days,
                        duration=duration,
                        motion=motion,
                    )

            actor = rig.render(t, layout.jake)
            shadow_width = round(225 - 3 * layout.jake.stretch + 4 * layout.jake.squat)
            shadow_y = 990
            draw.ellipse(
                (
                    360 - shadow_width // 2,
                    shadow_y - 10,
                    360 + shadow_width // 2,
                    shadow_y + 10,
                ),
                fill=(12, 16, 34, 145),
            )
            image.alpha_composite(actor, rig.placement(actor))

            # الكرة الأمامية تنرسم بعد الشخصية، فيصير occlusion حقيقي بدل طبقة واحدة.
            for index, (ball, motion) in enumerate(zip(balls, layout.balls)):
                if motion.front:
                    _draw_ball_with_blur(
                        image,
                        ball,
                        t=t,
                        index=index,
                        days=days,
                        duration=duration,
                        motion=motion,
                    )

            # Milestones تحصل على pulse بصري قصير قرب النهاية.
            if timeline.milestone_flash > 0.01:
                flash_alpha = round(145 * timeline.milestone_flash)
                draw.ellipse(
                    (112, 350, 608, 980),
                    outline=(255, 220, 120, flash_alpha),
                    width=4,
                )
                draw.ellipse(
                    (142, 382, 578, 948),
                    outline=(255, 255, 255, flash_alpha // 2),
                    width=2,
                )

            _animated_centered(
                image,
                "ستريك متتالي",
                y=210,
                size=46,
                fill="white",
                alpha=timeline.title_alpha,
                scale=timeline.title_scale,
            )
            _animated_centered(
                image,
                f"لـ {days} يوم",
                y=282,
                size=66,
                fill="#ffd56b",
                alpha=timeline.days_alpha,
                scale=timeline.days_scale,
            )
            _animated_centered(
                image,
                "كل يوم، أقرب",
                y=1055,
                size=29,
                fill="#e1e4fa",
                alpha=timeline.footer_alpha,
                scale=1.0,
            )
            _animated_centered(
                image,
                "STREAK TOGETHER",
                y=1110,
                size=15,
                fill="#919aba",
                alpha=timeline.footer_alpha,
                scale=1.0,
            )

            image.convert("RGB").save(
                frames / f"{frame:04}.jpg",
                quality=95,
                subsampling=0,
            )
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
                "24",
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
            timeout=180,
            capture_output=True,
        )
        return output
