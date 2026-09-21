from __future__ import annotations

import math
import random
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass
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



@dataclass(frozen=True, slots=True)
class _BallMotion:
    center: tuple[float, float]
    scale_x: float
    scale_y: float
    airborne: bool


@dataclass(frozen=True, slots=True)
class _MotionLayout:
    jake_width_scale: float
    jake_height_scale: float
    jake_y: float
    chain_amplitude: float
    balls: tuple[_BallMotion, _BallMotion]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _damped_spring(dt: float, *, frequency: float = 2.5, damping: float = 4.2) -> float:
    if dt < 0:
        return 0.0
    return math.exp(-damping * dt) * math.sin(2 * math.pi * frequency * dt)


def _ball_motion(t: float, index: int) -> _BallMotion:
    """رمي بين اليدين بسرعة أفقية ثابتة وقوس رأسي تحكمه الجاذبية."""
    if index not in (0, 1):
        raise ValueError("ball index must be 0 or 1")

    hands = ((205.0, 655.0), (515.0, 655.0))
    warmup = 0.35
    stagger = 0.90
    flight = 1.35
    hold = 0.45
    period = flight + hold
    shifted = t - warmup - index * stagger

    if shifted < 0:
        return _BallMotion(hands[index], 1.0, 1.0, False)

    cycle = int(shifted // period)
    local = shifted - cycle * period
    start_hand = (index + cycle) % 2
    end_hand = 1 - start_hand
    start_x, start_y = hands[start_hand]
    end_x, end_y = hands[end_hand]

    if local < flight:
        # المعادلة تجعل نقطة البداية والنهاية على نفس الارتفاع،
        # والقمة بارتفاع 190px بالمنتصف.
        rise = 190.0
        gravity = 8.0 * rise / (flight * flight)
        velocity_y = -0.5 * gravity * flight
        progress = local / flight
        x = start_x + (end_x - start_x) * progress
        y = start_y + velocity_y * local + 0.5 * gravity * local * local

        # تمدد طفيف مع السرعة العمودية فقط، بدون قوس/تكبير مصطنع.
        vertical_speed = abs(velocity_y + gravity * local) / abs(velocity_y)
        stretch = 0.018 * vertical_speed
        return _BallMotion(
            (x, y),
            1.0 - stretch * 0.55,
            1.0 + stretch,
            True,
        )

    caught = local - flight
    # الالتقاط يمتص الحركة خلال أجزاء من الثانية ثم ترجع الكرة لطبيعتها.
    impact = math.exp(-10.0 * caught)
    bounce = 4.0 * _damped_spring(caught, frequency=3.4, damping=8.0)
    return _BallMotion(
        (end_x, end_y + bounce),
        1.0 + 0.025 * impact,
        1.0 - 0.035 * impact,
        False,
    )


def _jake_reaction(t: float) -> float:
    """رد فعل نابضي على الرميات والالتقاطات المتعاقبة."""
    reaction = 0.0
    # هناك حدث رمي كل 0.9 ثانية، وبعده التقاط بعد 1.35 ثانية.
    first_launch = 0.35
    step = 0.90
    flight = 1.35
    event = first_launch
    while event <= t + 0.001:
        reaction += 0.75 * _damped_spring(t - event, frequency=2.1, damping=4.8)
        reaction -= 0.55 * _damped_spring(
            t - (event + flight),
            frequency=2.8,
            damping=6.0,
        )
        event += step
    return max(-1.2, min(1.2, reaction))


def _motion_layout(t: float) -> _MotionLayout:
    t = max(0.0, float(t))
    reaction = _jake_reaction(t)
    chain_wave = math.sin(2 * math.pi * t / 2.35)

    # squash/stretch محافظ على الحجم تقريبًا ويستجيب للرمي والالتقاط.
    height_scale = max(0.94, min(1.065, 1.0 + 0.040 * reaction))
    width_scale = max(0.95, min(1.055, 1.0 - 0.026 * reaction))
    jake_y = 805.0 - 6.0 * reaction + 2.0 * chain_wave
    chain_amplitude = 7.0 + 2.0 * abs(reaction)

    return _MotionLayout(
        jake_width_scale=width_scale,
        jake_height_scale=height_scale,
        jake_y=jake_y,
        chain_amplitude=chain_amplitude,
        balls=(_ball_motion(t, 0), _ball_motion(t, 1)),
    )


def _elastic_jake(
    source: Image.Image,
    t: float,
    *,
    width_scale: float,
    height_scale: float,
    chain_amplitude: float,
) -> Image.Image:
    """تشويه rubber-hose بسيط: أجزاء الجسم تتبع بعضها بتأخير بدل دوران الجسم كله."""
    width = max(1, round(source.width * width_scale))
    height = max(1, round(source.height * height_scale))
    actor = source.resize((width, height), Image.Resampling.LANCZOS)

    padding = max(4, math.ceil(chain_amplitude) + 4)
    result = Image.new("RGBA", (width + 2 * padding, height), (0, 0, 0, 0))
    bands = 18

    for band in range(bands):
        top = round(height * band / bands)
        bottom = round(height * (band + 1) / bands)
        if bottom <= top:
            continue

        center = (top + bottom) / (2 * height)
        # القدمين شبه ثابتة، وكل جزء أعلى يتأخر أكثر عن الجزء اللي تحته.
        follow = (1.0 - center) ** 0.72
        phase_delay = (1.0 - center) * 0.82
        offset = round(
            chain_amplitude
            * follow
            * math.sin(2 * math.pi * t / 2.05 - phase_delay)
        )

        crop_top = max(0, top - 1)
        crop_bottom = min(height, bottom + 1)
        strip = actor.crop((0, crop_top, width, crop_bottom))
        result.alpha_composite(strip, (padding + offset, crop_top))

    return result



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
                rng.randrange(30, WIDTH - 30),
                rng.randrange(360, 1060),
                rng.choice(palette),
                rng.uniform(12, 28),
            )
            for _ in range(30)
        ]
        for frame in range(duration * FPS):
            t = frame / FPS
            layout = _motion_layout(t)
            image = background.copy().convert("RGBA")
            draw = ImageDraw.Draw(image)

            # قصاصات قليلة وبطيئة؛ تبقى خلف الشخصيات بدل ما تصير ضوضاء مستمرة.
            for x, y, color, speed in confetti:
                yy = 360 + ((y - 360 + t * speed) % 700)
                if not (520 < yy < 1010 and 125 < x < 595):
                    draw.rounded_rectangle(
                        (x, yy, x + 4, yy + 8), radius=2, fill=color
                    )

            actor = _elastic_jake(
                jake,
                t,
                width_scale=layout.jake_width_scale,
                height_scale=layout.jake_height_scale,
                chain_amplitude=layout.chain_amplitude,
            )
            shadow_width = round(228 * layout.jake_width_scale)
            shadow_y = round(layout.jake_y + actor.height * 0.47)
            draw.ellipse(
                (
                    360 - shadow_width // 2,
                    shadow_y - 10,
                    360 + shadow_width // 2,
                    shadow_y + 10,
                ),
                fill=(12, 16, 34, 150),
            )
            image.alpha_composite(
                actor,
                (
                    360 - actor.width // 2,
                    round(layout.jake_y - actor.height / 2),
                ),
            )

            # رمي حقيقي: المحور الرأسي بالجاذبية، والكرة تستقر لحظة باليد قبل الرمية التالية.
            for index, ball in enumerate(balls):
                motion = layout.balls[index]
                ball_width = max(1, round(192 * motion.scale_x))
                ball_height = max(1, round(192 * motion.scale_y))
                actor_ball = ball.resize(
                    (ball_width, ball_height),
                    Image.Resampling.LANCZOS,
                )
                x, y = motion.center
                image.alpha_composite(
                    actor_ball,
                    (
                        round(x - actor_ball.width / 2),
                        round(y - actor_ball.height / 2),
                    ),
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
                "25",
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
