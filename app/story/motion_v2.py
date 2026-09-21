from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw

FPS = 30
HAND_Y = 655.0
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
            max(0.0, hold - caught),
            max(0.0, caught),
        )

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
        impact = math.exp(-11.0 * caught)
        bounce = 5.0 * damped_spring(caught, frequency=3.4, damping=8.5)
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
        )

    # آخر جزء من الفيديو يلتقط الكرتين ويثبتهم بدل ما ينقطع الفيديو وسط رمية.
    finale_start = max(0.0, duration - 0.72)
    if t > finale_start:
        amount = smoothstep((t - finale_start) / 0.62)
        target = (190.0, 665.0) if index == 0 else (530.0, 665.0)
        return BallMotion(
            (
                motion.center[0] + (target[0] - motion.center[0]) * amount,
                motion.center[1] + (target[1] - motion.center[1]) * amount,
            ),
            motion.scale_x + (1.0 - motion.scale_x) * amount,
            motion.scale_y + (1.0 - motion.scale_y) * amount,
            motion.airborne and amount < 0.8,
            motion.progress,
            motion.source_hand,
            motion.target_hand,
            True,
            motion.vertical_velocity * (1.0 - amount),
            motion.time_to_launch,
            motion.time_since_catch,
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


def _event_reaction(t: float, *, days: int, duration: int) -> float:
    reaction = 0.0
    for index in range(2):
        shifted = t - 0.82 - index * 0.64
        if shifted < 0:
            continue
        elapsed = shifted
        cycle = 0
        event_time = 0.82 + index * 0.64
        while True:
            flight, _ = _flight_parameters(cycle=cycle, days=days, duration=duration)
            period = flight + 0.34
            if elapsed < period:
                reaction += 0.72 * damped_spring(
                    t - event_time,
                    frequency=2.2,
                    damping=5.0,
                )
                reaction -= 0.52 * damped_spring(
                    t - (event_time + flight),
                    frequency=2.9,
                    damping=6.4,
                )
                break
            elapsed -= period
            event_time += period
            cycle += 1
    return max(-1.2, min(1.2, reaction))


def _hand_offsets(
    balls: tuple[BallMotion, BallMotion],
) -> tuple[tuple[float, float], tuple[float, float]]:
    offsets = [[0.0, 0.0], [0.0, 0.0]]

    for motion in balls:
        if motion.airborne:
            # follow-through بعد الإفلات.
            if motion.progress < 0.18:
                amount = 1.0 - motion.progress / 0.18
                offsets[motion.source_hand][0] += (
                    7.0 if motion.source_hand == 0 else -7.0
                ) * amount
                offsets[motion.source_hand][1] -= 8.0 * amount

            # اليد المستقبلة تطلع باتجاه الكرة قبل الالتقاط.
            if motion.progress > 0.76:
                amount = smoothstep((motion.progress - 0.76) / 0.24)
                hand_x, hand_y = LEFT_HAND if motion.target_hand == 0 else RIGHT_HAND
                offsets[motion.target_hand][0] += (
                    motion.center[0] - hand_x
                ) * 0.18 * amount
                offsets[motion.target_hand][1] += (
                    motion.center[1] - hand_y
                ) * 0.22 * amount
        else:
            # anticipation قبل الرمية: اليد تنزل للخلف لحظة ثم تنطلق.
            if 0.0 < motion.time_to_launch < 0.20:
                amount = smoothstep((0.20 - motion.time_to_launch) / 0.20)
                hand = motion.target_hand if motion.time_since_catch > 0 else motion.source_hand
                offsets[hand][0] += (-9.0 if hand == 0 else 9.0) * amount
                offsets[hand][1] += 11.0 * amount

            # امتصاص الالتقاط بدل توقف الكرة واليد بشكل مفاجئ.
            if 0.0 <= motion.time_since_catch < 0.18:
                amount = 1.0 - smoothstep(motion.time_since_catch / 0.18)
                offsets[motion.target_hand][1] += 8.0 * amount

    return (
        (offsets[0][0], offsets[0][1]),
        (offsets[1][0], offsets[1][1]),
    )


def _blink_amount(t: float) -> float:
    # رمشتان قصيرتان كل 4.2 ثانية، بدون randomness حتى الرندر reproducible.
    phase = t % 4.2
    for center in (1.75, 1.90):
        distance = abs(phase - center)
        if distance < 0.075:
            return max(0.0, 1.0 - distance / 0.075)
    return 0.0


def motion_layout(
    t: float,
    *,
    days: int,
    duration: int,
) -> MotionLayout:
    t = max(0.0, float(t))
    balls = (
        ball_motion(t, 0, days=days, duration=duration),
        ball_motion(t, 1, days=days, duration=duration),
    )
    reaction = _event_reaction(t, days=days, duration=duration)
    idle = math.sin(2 * math.pi * t / 2.55)

    height_scale = max(0.935, min(1.070, 1.0 + 0.042 * reaction))
    width_scale = max(0.945, min(1.060, 1.0 - 0.028 * reaction))
    intro = smoothstep(t / 0.55)
    center_y = 820.0 - 15.0 * intro - 6.0 * reaction + 2.0 * idle
    sway = 7.0 * math.sin(2 * math.pi * t / 2.05) + 2.5 * reaction
    head_nod = 2.5 * math.sin(2 * math.pi * t / 2.9) - 2.0 * reaction

    return MotionLayout(
        jake=JakePose(
            width_scale=width_scale,
            height_scale=height_scale,
            center_y=center_y,
            sway=sway,
            head_nod=head_nod,
            hand_offsets=_hand_offsets(balls),
            blink=_blink_amount(t),
        ),
        balls=balls,
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
        (duration - 0.68, round((14 if not style.enabled else 32) * style.confetti_scale), 600.0),
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
                    if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] and (nx, ny) not in seen:
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
        row_x = [x for x in range(max(0, left), min(image.width, right)) if alpha_pixels[x, y] > 64]
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
        box for box in boxes
        if box[3] - box[1] <= height * 0.16
        and box[2] - box[0] <= width * 0.20
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


def _sample_skin_color(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
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
    pixels = [
        px for px in crop.getdata()
        if px[3] > 100 and max(px[:3]) > 110
    ]
    if not pixels:
        return (240, 181, 44, 255)
    # المتوسط مقاوم كفاية لأن المساحة حول العين صغيرة.
    r = round(sum(px[0] for px in pixels) / len(pixels))
    g = round(sum(px[1] for px in pixels) / len(pixels))
    b = round(sum(px[2] for px in pixels) / len(pixels))
    return (r, g, b, 255)


class JakeRig:
    """Rig برمجي مبني من silhouette الأصل، بدون ملفات أطراف منفصلة."""

    def __init__(self, source: Image.Image):
        self.source = source.convert("RGBA")
        self.landmarks = detect_landmarks(self.source)

    def _with_blink(self, amount: float) -> Image.Image:
        if amount <= 0.03 or len(self.landmarks.eye_boxes) != 2:
            return self.source
        image = self.source.copy()
        draw = ImageDraw.Draw(image)
        for box in self.landmarks.eye_boxes:
            left, top, right, bottom = box
            skin = _sample_skin_color(image, box)
            draw.rounded_rectangle(
                (left - 2, top - 2, right + 2, bottom + 2),
                radius=3,
                fill=skin,
            )
            center_y = (top + bottom) / 2
            eye_width = max(4, right - left)
            line_half = eye_width * (0.35 + 0.15 * amount)
            center_x = (left + right) / 2
            draw.line(
                (center_x - line_half, center_y, center_x + line_half, center_y),
                fill=(35, 29, 20, 255),
                width=max(1, round(2 * amount)),
            )
        return image

    def render(self, t: float, pose: JakePose) -> Image.Image:
        source = self._with_blink(pose.blink)
        width = max(1, round(source.width * pose.width_scale))
        height = max(1, round(source.height * pose.height_scale))
        actor = source.resize((width, height), Image.Resampling.LANCZOS)

        pad = 28
        canvas = Image.new("RGBA", (width + pad * 2, height + pad * 2), (0, 0, 0, 0))
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
            dx = pose.sway * (1.0 - normalized_y) ** 0.72
            dy = 0.0

            # الرأس يتبع الجسم لكن بتأخير/نود خفيف.
            head_distance = ((x - head[0]) / 105.0) ** 2 + ((y - head[1]) / 90.0) ** 2
            head_weight = math.exp(-2.2 * head_distance)
            dy += pose.head_nod * head_weight
            dx += pose.sway * 0.20 * head_weight

            # كل يد لها joint محلي يتبع الكرة قبل الالتقاط وبعد الرمي.
            for anchor, offset in zip(
                (left_hand, right_hand),
                pose.hand_offsets,
            ):
                distance = ((x - anchor[0]) / 105.0) ** 2 + ((y - anchor[1]) / 92.0) ** 2
                weight = math.exp(-2.6 * distance)
                dx += offset[0] * weight
                dy += offset[1] * weight

            return dx, dy

        cols = 8
        rows = 10
        cell_w = canvas.width / cols
        cell_h = canvas.height / rows
        mesh = []

        for row in range(rows):
            for col in range(cols):
                x0 = round(col * cell_w)
                y0 = round(row * cell_h)
                x1 = round((col + 1) * cell_w)
                y1 = round((row + 1) * cell_h)
                corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
                source_quad: list[float] = []
                for x, y in corners:
                    dx, dy = displacement(x, y)
                    source_quad.extend((x - dx, y - dy))
                mesh.append(((x0, y0, x1, y1), tuple(source_quad)))

        return canvas.transform(
            canvas.size,
            Image.Transform.MESH,
            mesh,
            resample=Image.Resampling.BICUBIC,
        )
