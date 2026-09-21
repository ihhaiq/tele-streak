from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

FPS = 30
RIG_SUPERSAMPLE = 1.25
# Ball centers sit one radius above the raised palms.
HAND_Y = 558.0
LEFT_HAND = (205.0, HAND_Y)
RIGHT_HAND = (515.0, HAND_Y)
MILESTONES = {7, 30, 50, 100, 365}


@dataclass(frozen=True, slots=True)
class MilestoneStyle:
    enabled: bool
    toss_scale: float
    confetti_scale: float
    finale_scale: float


@dataclass(frozen=True, slots=True)
class BallMotion:
    center: tuple[float, float]
    scale_x: float
    scale_y: float
    airborne: bool
    progress: float
    source_hand: int
    target_hand: int
    front: bool
    vertical_velocity: float
    time_to_launch: float
    time_since_catch: float


@dataclass(frozen=True, slots=True)
class JakePose:
    width_scale: float
    height_scale: float
    center_y: float
    sway: float
    head_nod: float
    hand_offsets: tuple[tuple[float, float], tuple[float, float]]
    blink: float
    smile: float = 0.0
    mouth_open: float = 0.0
    gaze: tuple[float, float] = (0.0, 0.0)
    squat: float = 0.0
    stretch: float = 0.0
    heel_lift: tuple[float, float] = (0.0, 0.0)
    hip_sway: float = 0.0
    pose_name: str = "idle"


@dataclass(frozen=True, slots=True)
class MotionLayout:
    jake: JakePose
    balls: tuple[BallMotion, BallMotion]


@dataclass(frozen=True, slots=True)
class TimelineState:
    title_alpha: float
    title_scale: float
    days_alpha: float
    days_scale: float
    footer_alpha: float
    finale: float
    milestone_flash: float


@dataclass(frozen=True, slots=True)
class ConfettiParticle:
    birth: float
    x: float
    y: float
    vx: float
    vy: float
    gravity: float
    size: float
    rotation: float
    spin: float
    color_index: int
    lifetime: float


@dataclass(frozen=True, slots=True)
class RigLandmarks:
    bbox: tuple[int, int, int, int]
    left_hand: tuple[float, float]
    right_hand: tuple[float, float]
    head_center: tuple[float, float]
    eye_boxes: tuple[tuple[int, int, int, int], ...]


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def smoothstep(value: float) -> float:
    value = clamp01(value)
    return value * value * (3.0 - 2.0 * value)


def ease_out_back(value: float) -> float:
    value = clamp01(value)
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (value - 1.0) ** 3 + c1 * (value - 1.0) ** 2


def damped_spring(
    dt: float,
    *,
    frequency: float = 2.5,
    damping: float = 4.2,
) -> float:
    if dt < 0:
        return 0.0
    return math.exp(-damping * dt) * math.sin(2 * math.pi * frequency * dt)


def milestone_style(days: int) -> MilestoneStyle:
    if days not in MILESTONES:
        return MilestoneStyle(False, 1.0, 1.0, 1.0)
    if days >= 100:
        return MilestoneStyle(True, 1.22, 1.7, 1.10)
    if days >= 30:
        return MilestoneStyle(True, 1.15, 1.45, 1.07)
    return MilestoneStyle(True, 1.10, 1.25, 1.05)


def _flight_parameters(
    *,
    cycle: int,
    days: int,
    duration: int,
) -> tuple[float, float]:
    flight = 1.30
    rise = 185.0
    style = milestone_style(days)

    # فيديو 10 ثواني ما يكرر نفس الحركة حرفيًا؛ كل رمية رابعة تكون أعلى شوي.
    if duration >= 10 and cycle % 4 == 2:
        flight = 1.46
        rise = 230.0

    # الأيام المهمة تحصل على رمية أوضح بدون قلب الفيزياء.
    if style.enabled and cycle % 3 == 1:
        rise *= style.toss_scale
        flight *= 1.04

    return flight, rise


def ball_motion(
    t: float,
    index: int,
    *,
    days: int,
    duration: int,
) -> BallMotion:
    if index not in (0, 1):
        raise ValueError("ball index must be 0 or 1")

    warmup = 0.82
    stagger = 0.64
    hold = 0.34
    shifted = t - warmup - index * stagger

    if shifted < 0:
        hand = index
        center = LEFT_HAND if hand == 0 else RIGHT_HAND
        return BallMotion(
            center,
            1.0,
            1.0,
            False,
            0.0,
            hand,
            1 - hand,
            index == 0,
            0.0,
            -shifted,
            0.0,
        )

    last_cycle = -1
    end = warmup + stagger
    while True:
        next_flight, _ = _flight_parameters(
            cycle=last_cycle + 1, days=days, duration=duration
        )
        if end + next_flight > duration - 0.50:
            break
        last_cycle += 1
        end += next_flight + hold

    # نحتاج دورة متغيرة لأن بعض رميات 10s/milestone أطول.
    elapsed = shifted
    cycle = 0
    while True:
        flight, _ = _flight_parameters(cycle=cycle, days=days, duration=duration)
        period = flight + hold
        if elapsed < period:
            break
        elapsed -= period
        cycle += 1

    if cycle > last_cycle:
        hand = (index + last_cycle + 1) % 2
        center = LEFT_HAND if hand == 0 else RIGHT_HAND
        return BallMotion(
            center, 1.0, 1.0, False, 1.0, 1 - hand, hand, True, 0.0, math.inf, math.inf
        )
    flight, rise = _flight_parameters(cycle=cycle, days=days, duration=duration)
    local = elapsed
    source_hand = (index + cycle) % 2
    target_hand = 1 - source_hand
    start_x, start_y = LEFT_HAND if source_hand == 0 else RIGHT_HAND
    end_x, end_y = LEFT_HAND if target_hand == 0 else RIGHT_HAND

    if local < flight:
        gravity = 8.0 * rise / (flight * flight)
        velocity_y = -0.5 * gravity * flight
        progress = local / flight

        # أفقيًا تمشي الكرة بسلاسة بين اليدين، عموديًا تحكمها الجاذبية.
        x_progress = smoothstep(progress * 0.94 + 0.03)
        x = start_x + (end_x - start_x) * x_progress
        y = start_y + velocity_y * local + 0.5 * gravity * local * local
        current_vy = velocity_y + gravity * local

        vertical_speed = min(1.0, abs(current_vy) / max(1.0, abs(velocity_y)))
        stretch = 0.024 * vertical_speed
        front = (cycle + index) % 2 == 0

        motion = BallMotion(
            (x, y),
            1.0 - stretch * 0.50,
            1.0 + stretch,
            True,
            progress,
            source_hand,
            target_hand,
            front,
            current_vy,
            0.0,
            0.0,
        )
    else:
        caught = local - flight
        if cycle == last_cycle and caught >= 0.27:
            return BallMotion(
                (end_x, end_y),
                1.0,
                1.0,
                False,
                1.0,
                source_hand,
                target_hand,
                True,
                0.0,
                math.inf,
                math.inf,
            )
        impact = 1.0 - smoothstep(caught / 0.27)
        bounce = 5.0 * damped_spring(caught, frequency=3.4, damping=8.5) * impact
        motion = BallMotion(
            (end_x, end_y + bounce),
            1.0 + 0.030 * impact,
            1.0 - 0.042 * impact,
            False,
            1.0,
            source_hand,
            target_hand,
            (cycle + index) % 2 == 0,
            0.0,
            max(0.0, hold - caught) if cycle < last_cycle else math.inf,
            max(0.0, caught),
        )

    return motion


def motion_blur_samples(
    t: float,
    index: int,
    *,
    days: int,
    duration: int,
) -> tuple[tuple[BallMotion, int], ...]:
    current = ball_motion(t, index, days=days, duration=duration)
    if not current.airborne or abs(current.vertical_velocity) < 80:
        return ()

    samples: list[tuple[BallMotion, int]] = []
    for offset, alpha in ((0.020, 62), (0.040, 34), (0.060, 16)):
        sample_t = max(0.0, t - offset)
        sample = ball_motion(sample_t, index, days=days, duration=duration)
        if sample.airborne:
            samples.append((sample, alpha))
    return tuple(samples)


def _events(t: float, days: int, duration: int):
    """Same launch schedule as the balls; pulses have zero slope at their edges."""
    start = 0.82
    cycle = 0
    while True:
        flight, _ = _flight_parameters(cycle=cycle, days=days, duration=duration)
        if start + 0.64 + flight > duration - 0.50:
            break
        for index in range(2):
            launch = start + index * 0.64
            yield (index + cycle) % 2, launch, launch + flight
        start += flight + 0.34
        cycle += 1


def _pulse(t: float, start: float, peak: float, end: float) -> float:
    if t < start or t > end:
        return 0.0
    if t <= peak:
        return smoothstep((t - start) / (peak - start))
    return 1.0 - smoothstep((t - peak) / (end - peak))


def _blink_amount(t: float) -> float:
    phase = t % 4.2
    return max(_pulse(phase, c - 0.11, c, c + 0.15) for c in (1.75, 3.65))


def motion_layout(t: float, *, days: int, duration: int) -> MotionLayout:
    t = max(0.0, min(float(duration), float(t)))
    balls = tuple(ball_motion(t, i, days=days, duration=duration) for i in range(2))
    hands = [[0.0, 0.0], [0.0, 0.0]]
    heels = [0.0, 0.0]
    anticipation = release = catch = lean = secondary = joy = 0.0
    for hand, launch, landing in _events(t, days, duration):
        direction = 1.0 if hand == 0 else -1.0
        prep = _pulse(t, launch - 0.30, launch - 0.14, launch + 0.04)
        throw = _pulse(t, launch - 0.08, launch + 0.12, launch + 0.40)
        reach = _pulse(t, landing - 0.28, landing - 0.08, landing + 0.13)
        absorb = _pulse(t, landing - 0.06, landing + 0.10, landing + 0.27)
        hands[hand][0] += direction * (-10 * prep + 11 * throw)
        hands[hand][1] += 12 * prep - 12 * throw
        hands[1 - hand][0] += direction * 6 * reach
        hands[1 - hand][1] += -9 * reach + 9 * absorb
        anticipation += prep
        release += throw
        catch += absorb
        lean += direction * (throw - 0.6 * prep - 0.5 * absorb)
        heels[1 - hand] += 3.0 * throw
        secondary += direction * _pulse(t, launch + 0.04, launch + 0.18, launch + 0.48)
        joy += 0.45 * throw + 0.65 * _pulse(t, landing, landing + 0.13, landing + 0.4)

    finale = smoothstep((t - (duration - 0.55)) / 0.30)
    active = 1.0 - finale
    squat = min(1.0, anticipation + 0.55 * catch) * active
    stretch = min(1.0, release) * active
    # Follow both balls continuously; no abrupt choice of an active ball.
    gaze_x = sum(ball.center[0] - 360 for ball in balls) / 310
    gaze_y = sum(ball.center[1] - HAND_Y for ball in balls) / 400
    excited = min(1.0, joy) * active
    milestone = milestone_style(days).enabled
    pose_name = (
        "celebration"
        if finale > 0.5
        else (
            "pre-throw"
            if anticipation > 0.3
            else "catch" if catch > 0.2 else "throw" if release > 0.2 else "idle"
        )
    )
    return MotionLayout(
        JakePose(
            width_scale=1.0,
            height_scale=1.0,
            center_y=805.0,
            sway=6.0 * lean * active,
            head_nod=(-1.8 * secondary + 0.8 * catch) * active,
            hand_offsets=tuple((x * active, y * active) for x, y in hands),
            blink=_blink_amount(t) * active,
            smile=0.25 + 0.4 * excited + (0.65 if milestone else 0.5) * finale,
            mouth_open=0.35 * excited + (0.80 if milestone else 0.5) * finale,
            gaze=(
                max(-1.0, min(1.0, gaze_x)) * active,
                max(-1.0, min(0.2, gaze_y)) * active,
            ),
            squat=squat,
            stretch=stretch,
            heel_lift=tuple(min(3.0, h) * active for h in heels),
            hip_sway=1.8 * lean * active,
            pose_name=pose_name,
        ),
        balls,
    )


def timeline_state(
    t: float,
    *,
    duration: int,
    days: int,
) -> TimelineState:
    title = smoothstep(t / 0.40)
    title_scale = 0.92 + 0.08 * ease_out_back(t / 0.52)
    days_progress = clamp01((t - 0.28) / 0.48)
    days_alpha = smoothstep(days_progress)
    days_scale = 0.72 + 0.28 * ease_out_back(days_progress)
    footer = smoothstep((t - 0.65) / 0.50)
    finale = smoothstep((t - (duration - 0.85)) / 0.65)

    style = milestone_style(days)
    flash = 0.0
    if style.enabled:
        flash = max(
            0.0,
            1.0 - abs(t - (duration - 0.48)) / 0.28,
        )

    return TimelineState(
        title_alpha=title,
        title_scale=title_scale,
        days_alpha=days_alpha,
        days_scale=days_scale,
        footer_alpha=footer,
        finale=finale,
        milestone_flash=flash,
    )


def confetti_particles(days: int, duration: int) -> tuple[ConfettiParticle, ...]:
    style = milestone_style(days)
    rng = random.Random(0x5A17 + days * 17 + duration)
    particles: list[ConfettiParticle] = []

    bursts = [
        (0.12, round(24 * style.confetti_scale), 315.0),
        (
            duration - 0.68,
            round((14 if not style.enabled else 32) * style.confetti_scale),
            600.0,
        ),
    ]

    for birth, count, origin_y in bursts:
        for _ in range(count):
            origin_x = rng.uniform(105.0, 615.0)
            direction = -1.0 if origin_x > 360.0 else 1.0
            particles.append(
                ConfettiParticle(
                    birth=max(0.0, birth + rng.uniform(-0.08, 0.08)),
                    x=origin_x,
                    y=origin_y + rng.uniform(-24.0, 24.0),
                    vx=direction * rng.uniform(25.0, 115.0) + rng.uniform(-35.0, 35.0),
                    vy=-rng.uniform(110.0, 285.0),
                    gravity=rng.uniform(190.0, 280.0),
                    size=rng.uniform(4.0, 8.0),
                    rotation=rng.uniform(0.0, 360.0),
                    spin=rng.uniform(-260.0, 260.0),
                    color_index=rng.randrange(4),
                    lifetime=rng.uniform(1.6, 2.6),
                )
            )

    return tuple(particles)


def confetti_state(
    particle: ConfettiParticle,
    t: float,
) -> tuple[float, float, float, int] | None:
    age = t - particle.birth
    if age < 0.0 or age > particle.lifetime:
        return None

    x = particle.x + particle.vx * age
    y = particle.y + particle.vy * age + 0.5 * particle.gravity * age * age
    rotation = particle.rotation + particle.spin * age
    fade = 1.0
    if age > particle.lifetime - 0.45:
        fade = clamp01((particle.lifetime - age) / 0.45)
    return x, y, rotation, round(255 * fade)


def ball_shadow(motion: BallMotion) -> tuple[float, float, float, int]:
    altitude = max(0.0, HAND_Y - motion.center[1])
    ratio = clamp01(altitude / 220.0)
    width = 56.0 - 26.0 * ratio
    alpha = round(90 - 55 * ratio)
    return motion.center[0], 704.0, width, alpha


def _component_boxes(mask: Image.Image) -> list[tuple[int, int, int, int]]:
    width, height = mask.size
    pixels = mask.load()
    seen: set[tuple[int, int]] = set()
    boxes: list[tuple[int, int, int, int]] = []

    for y in range(height):
        for x in range(width):
            if not pixels[x, y] or (x, y) in seen:
                continue
            stack = [(x, y)]
            seen.add((x, y))
            xs: list[int] = []
            ys: list[int] = []
            while stack:
                px, py = stack.pop()
                xs.append(px)
                ys.append(py)
                for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
                    if (
                        0 <= nx < width
                        and 0 <= ny < height
                        and pixels[nx, ny]
                        and (nx, ny) not in seen
                    ):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if 3 <= len(xs) <= 500:
                boxes.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return boxes


def detect_landmarks(source: Image.Image) -> RigLandmarks:
    image = source.convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox() or (0, 0, image.width, image.height)
    left, top, right, bottom = bbox
    width = max(1, right - left)
    height = max(1, bottom - top)

    # اليدين من أبعد نقطتين في منتصف الجسم، مو من إحداثيات ثابتة للصورة.
    band_top = round(top + height * 0.30)
    band_bottom = round(top + height * 0.66)
    alpha_pixels = alpha.load()
    left_point = (left + width * 0.22, top + height * 0.52)
    right_point = (left + width * 0.78, top + height * 0.52)
    min_x = image.width
    max_x = -1
    min_y = max_y = round(top + height * 0.52)

    for y in range(max(0, band_top), min(image.height, band_bottom)):
        row_x = [
            x
            for x in range(max(0, left), min(image.width, right))
            if alpha_pixels[x, y] > 64
        ]
        if not row_x:
            continue
        if row_x[0] < min_x:
            min_x = row_x[0]
            min_y = y
        if row_x[-1] > max_x:
            max_x = row_x[-1]
            max_y = y

    if min_x < image.width:
        left_point = (float(min_x), float(min_y))
    if max_x >= 0:
        right_point = (float(max_x), float(max_y))

    head_center = (left + width * 0.50, top + height * 0.23)

    # نبحث عن مكونات داكنة صغيرة في الجزء العلوي حتى نقدر نسوي blink على العينين.
    crop_bottom = max(top + 1, round(top + height * 0.42))
    rgb = image.convert("RGB")
    dark = Image.new("1", image.size, 0)
    dark_pixels = dark.load()
    rgb_pixels = rgb.load()
    for y in range(max(0, top), min(image.height, crop_bottom)):
        for x in range(max(0, left), min(image.width, right)):
            r, g, b = rgb_pixels[x, y]
            if alpha_pixels[x, y] > 100 and max(r, g, b) < 95:
                dark_pixels[x, y] = 1

    boxes = _component_boxes(dark)
    boxes = [
        box
        for box in boxes
        if box[3] - box[1] <= height * 0.16 and box[2] - box[0] <= width * 0.20
    ]
    boxes.sort(key=lambda box: ((box[1] + box[3]) / 2, box[0]))
    eye_boxes: tuple[tuple[int, int, int, int], ...] = ()
    for first in boxes:
        for second in boxes:
            if first is second:
                continue
            fy = (first[1] + first[3]) / 2
            sy = (second[1] + second[3]) / 2
            fx = (first[0] + first[2]) / 2
            sx = (second[0] + second[2]) / 2
            if abs(fy - sy) <= height * 0.06 and abs(fx - sx) >= width * 0.08:
                eye_boxes = tuple(sorted((first, second), key=lambda box: box[0]))
                break
        if eye_boxes:
            break

    return RigLandmarks(
        bbox=bbox,
        left_hand=left_point,
        right_hand=right_point,
        head_center=head_center,
        eye_boxes=eye_boxes,
    )


def _sample_skin_color(
    image: Image.Image, box: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad = 5
    crop = image.crop(
        (
            max(0, left - pad),
            max(0, top - pad),
            min(image.width, right + pad),
            min(image.height, bottom + pad),
        )
    ).convert("RGBA")
    pixels = [px for px in crop.getdata() if px[3] > 100 and max(px[:3]) > 110]
    if not pixels:
        return (240, 181, 44, 255)
    # المتوسط مقاوم كفاية لأن المساحة حول العين صغيرة.
    r = round(sum(px[0] for px in pixels) / len(pixels))
    g = round(sum(px[1] for px in pixels) / len(pixels))
    b = round(sum(px[2] for px in pixels) / len(pixels))
    return (r, g, b, 255)


class JakeRig:
    """Rig برمجي مبني من silhouette الأصل، بدون ملفات أطراف منفصلة."""

    def __init__(self, source: Image.Image, *, celebration: bool = False):
        self.source = source.convert("RGBA")
        self.landmarks = detect_landmarks(self.source)
        self.celebration = celebration
        if celebration:
            # Measured on celebration_art: the raised fists are above the torso.
            sx, sy = source.width / 420, source.height / 420
            self.landmarks = RigLandmarks(
                self.landmarks.bbox,
                (69 * sx, 59 * sy),
                (350 * sx, 59 * sy),
                (214 * sx, 116 * sy),
                tuple(
                    tuple(
                        round(v * (sx if i % 2 == 0 else sy)) for i, v in enumerate(box)
                    )
                    for box in ((155, 96, 197, 137), (231, 94, 271, 134))
                ),
            )

    def _with_face(self, pose: JakePose) -> Image.Image:
        if len(self.landmarks.eye_boxes) != 2:
            return self.source
        image = self.source.copy()
        draw = ImageDraw.Draw(image)
        for left, top, right, bottom in self.landmarks.eye_boxes:
            cx, cy = (left + right) / 2, (top + bottom) / 2
            rx, ry = (right - left) / 2, (bottom - top) / 2
            if self.celebration:
                # Keep the existing eye outline and muzzle; redraw only the interior.
                draw.ellipse(
                    (left + 3, top + 3, right - 3, bottom - 3),
                    fill=(255, 253, 241, 255),
                )
                px = cx + pose.gaze[0] * rx * 0.30
                py = cy + pose.gaze[1] * ry * 0.30
                radius = rx * 0.22
                draw.ellipse(
                    (px - radius, py - radius, px + radius, py + radius),
                    fill=(30, 25, 19, 255),
                )
            if pose.blink > 0:
                # Compress the complete eye continuously, instead of switching to a line.
                box = (left, top, right, bottom)
                eye = image.crop(box)
                skin = (
                    (248, 190, 34, 255)
                    if self.celebration
                    else _sample_skin_color(image, box)
                )
                draw.ellipse(box, fill=skin)
                eye_h = max(2, round((bottom - top) * (1 - 0.94 * pose.blink)))
                eye = eye.resize((right - left, eye_h), Image.Resampling.LANCZOS)
                image.alpha_composite(eye, (left, round(cy - eye_h / 2)))
        if self.celebration:
            sx, sy = image.width / 420, image.height / 420
            # The patch stays below the muzzle and does not touch the nose.
            mask = Image.new("L", image.size)
            ImageDraw.Draw(mask).polygon(
                [
                    (round(x * sx), round(y * sy))
                    for x, y in (
                        (201, 150),
                        (237, 150),
                        (240, 162),
                        (235, 175),
                        (222, 180),
                        (208, 177),
                        (200, 165),
                    )
                ],
                fill=255,
            )
            mask = mask.filter(ImageFilter.GaussianBlur(max(0.5, sx)))
            skin = Image.new("RGBA", image.size, (252, 191, 24, 253))
            skin_draw = ImageDraw.Draw(skin)
            for y in range(round(148 * sy), round(183 * sy)):
                color = self.source.getpixel((round(246 * sx), y))
                skin_draw.line((round(197 * sx), y, round(242 * sx), y), fill=color)
            image = Image.composite(skin, image, mask)
            draw = ImageDraw.Draw(image)
            width = (25 + 7 * pose.smile) * sx
            cx, top = 219 * sx, 148 * sy
            depth = (7 + 24 * pose.mouth_open) * sy
            box = (cx - width / 2, top, cx + width / 2, top + depth)
            if pose.mouth_open > 0.08:
                draw.ellipse(box, fill=(44, 24, 20, 255))
                draw.ellipse(
                    (
                        cx - width * 0.24,
                        top + depth * 0.60,
                        cx + width * 0.24,
                        top + depth * 0.94,
                    ),
                    fill=(235, 100, 111, 255),
                )
            else:
                draw.arc(
                    box, 0, 180, fill=(44, 24, 20, 255), width=max(2, round(2 * sx))
                )
        return image

    def placement(
        self, actor: Image.Image, *, floor_y: float = 990.0
    ) -> tuple[int, int]:
        # A fixed source-space sole, independent of head or body movement.
        sole = (28 + self.landmarks.bbox[3]) / (self.source.height + 56)
        return 360 - actor.width // 2, round(floor_y - sole * actor.height)

    def render(self, t: float, pose: JakePose) -> Image.Image:
        source = self._with_face(pose)
        final_width = max(1, round(source.width * pose.width_scale))
        final_height = max(1, round(source.height * pose.height_scale))
        width = max(1, round(final_width * RIG_SUPERSAMPLE))
        height = max(1, round(final_height * RIG_SUPERSAMPLE))
        actor = source.resize((width, height), Image.Resampling.LANCZOS)

        pad = round(28 * RIG_SUPERSAMPLE)
        canvas = Image.new(
            "RGBA",
            (width + pad * 2, height + pad * 2),
            (0, 0, 0, 0),
        )
        canvas.alpha_composite(actor, (pad, pad))

        sx = width / self.source.width
        sy = height / self.source.height
        left_hand = (
            pad + self.landmarks.left_hand[0] * sx,
            pad + self.landmarks.left_hand[1] * sy,
        )
        right_hand = (
            pad + self.landmarks.right_hand[0] * sx,
            pad + self.landmarks.right_hand[1] * sy,
        )
        head = (
            pad + self.landmarks.head_center[0] * sx,
            pad + self.landmarks.head_center[1] * sy,
        )

        def displacement(x: float, y: float) -> tuple[float, float]:
            normalized_y = clamp01((y - pad) / max(1.0, height))
            dx = pose.sway * RIG_SUPERSAMPLE * (1.0 - normalized_y) ** 0.72
            # Squat moves hips and upper body; the soles remain planted.
            planted = 1.0 - smoothstep((normalized_y - 0.72) / 0.20)
            dy = (7.0 * pose.squat - 3.0 * pose.stretch) * RIG_SUPERSAMPLE * planted
            hip_weight = math.exp(-(((normalized_y - 0.70) / 0.16) ** 2))
            dx += pose.hip_sway * RIG_SUPERSAMPLE * hip_weight

            # الرأس يتبع الجسم لكن بتأخير/نود خفيف.
            head_distance = ((x - head[0]) / 105.0) ** 2 + ((y - head[1]) / 90.0) ** 2
            head_weight = math.exp(-2.2 * head_distance)
            dy += pose.head_nod * RIG_SUPERSAMPLE * head_weight
            dx += pose.sway * RIG_SUPERSAMPLE * 0.20 * head_weight

            # Shoulder -> elbow -> wrist: two bounded segments, shared bend.
            for side, (anchor, offset) in enumerate(
                zip((left_hand, right_hand), pose.hand_offsets)
            ):
                shoulder = (
                    pad + width * (0.32 if side == 0 else 0.68),
                    pad + height * 0.45,
                )
                elbow = (
                    (shoulder[0] + anchor[0]) / 2,
                    (shoulder[1] + anchor[1]) / 2 + 5 * RIG_SUPERSAMPLE,
                )
                for joint, influence, radius in (
                    (elbow, 0.42, 48.0),
                    (anchor, 1.0, 42.0),
                ):
                    distance = ((x - joint[0]) / (radius * RIG_SUPERSAMPLE)) ** 2 + (
                        (y - joint[1]) / (radius * RIG_SUPERSAMPLE)
                    ) ** 2
                    weight = math.exp(-2.0 * distance)
                    dx += offset[0] * RIG_SUPERSAMPLE * weight * influence
                    dy += offset[1] * RIG_SUPERSAMPLE * weight * influence

                knee_x = pad + width * (0.31 if side == 0 else 0.69)
                knee_y = pad + height * 0.82
                knee_weight = math.exp(
                    -2 * ((x - knee_x) / (35 * RIG_SUPERSAMPLE)) ** 2
                    - 2 * ((y - knee_y) / (28 * RIG_SUPERSAMPLE)) ** 2
                )
                dx += (
                    (-1 if side == 0 else 1)
                    * 3
                    * pose.squat
                    * RIG_SUPERSAMPLE
                    * knee_weight
                )
                # Lift the inner heel while the outer toe stays on the floor.
                heel_x = pad + width * (0.31 if side == 0 else 0.69)
                heel_y = pad + height * 0.90
                heel_weight = math.exp(
                    -3 * ((x - heel_x) / (22 * RIG_SUPERSAMPLE)) ** 2
                    - 3 * ((y - heel_y) / (20 * RIG_SUPERSAMPLE)) ** 2
                )
                dy -= pose.heel_lift[side] * RIG_SUPERSAMPLE * heel_weight

            return dx, dy

        cols = 24
        rows = 28
        cell_w = canvas.width / cols
        cell_h = canvas.height / rows
        mesh = []

        for row in range(rows):
            for col in range(cols):
                x0 = round(col * cell_w)
                y0 = round(row * cell_h)
                x1 = round((col + 1) * cell_w)
                y1 = round((row + 1) * cell_h)
                corners = ((x0, y0), (x0, y1), (x1, y1), (x1, y0))
                source_quad: list[float] = []
                for x, y in corners:
                    dx, dy = displacement(x, y)
                    source_quad.extend((x - dx, y - dy))
                mesh.append(((x0, y0, x1, y1), tuple(source_quad)))

        warped = canvas.transform(
            canvas.size,
            Image.Transform.MESH,
            mesh,
            resample=Image.Resampling.BICUBIC,
        )
        return warped.resize(
            (
                max(1, round(warped.width / RIG_SUPERSAMPLE)),
                max(1, round(warped.height / RIG_SUPERSAMPLE)),
            ),
            Image.Resampling.LANCZOS,
        )
