from PIL import Image, ImageDraw

from app.story.motion_v2 import (
    FPS,
    JakeRig,
    _flight_parameters,
    ball_motion,
    ball_shadow,
    confetti_particles,
    confetti_state,
    milestone_style,
    motion_blur_samples,
    motion_layout,
    timeline_state,
)


def test_video_runs_at_30fps():
    assert FPS == 30


def test_ball_follows_gravity_arc_between_hands():
    flight, _ = _flight_parameters(cycle=0, days=5, duration=5)
    launch_t = 0.82
    launch = ball_motion(launch_t, 0, days=5, duration=5)
    quarter = ball_motion(launch_t + flight * 0.25, 0, days=5, duration=5)
    apex = ball_motion(launch_t + flight * 0.50, 0, days=5, duration=5)
    three_quarters = ball_motion(
        launch_t + flight * 0.75,
        0,
        days=5,
        duration=5,
    )

    assert launch.airborne
    assert apex.airborne
    assert launch.center[0] < apex.center[0]
    assert apex.center[0] < three_quarters.center[0]
    assert apex.center[1] < quarter.center[1]
    assert apex.center[1] < three_quarters.center[1]
    assert abs(quarter.center[1] - three_quarters.center[1]) < 0.01


def test_ball_accelerates_downward_after_apex():
    flight, _ = _flight_parameters(cycle=0, days=5, duration=5)
    launch_t = 0.82
    samples = [
        ball_motion(launch_t + flight * ratio, 0, days=5, duration=5)
        for ratio in (0.55, 0.65, 0.75, 0.85)
    ]

    first_drop = samples[2].center[1] - samples[1].center[1]
    second_drop = samples[3].center[1] - samples[2].center[1]
    assert first_drop > 0
    assert second_drop > first_drop


def test_catch_and_prelaunch_have_timing_state_for_hand_rig():
    flight, _ = _flight_parameters(cycle=0, days=5, duration=5)
    caught = ball_motion(0.82 + flight + 0.03, 0, days=5, duration=5)
    before_next = ball_motion(0.82 + flight + 0.30, 0, days=5, duration=5)

    assert not caught.airborne
    assert 0 < caught.time_since_catch < 0.10
    assert 0 < before_next.time_to_launch < 0.10

    caught_layout = motion_layout(
        0.82 + flight + 0.03,
        days=5,
        duration=5,
    )
    next_layout = motion_layout(
        0.82 + flight + 0.30,
        days=5,
        duration=5,
    )
    assert caught_layout.jake.hand_offsets[1][1] > 0
    assert next_layout.jake.hand_offsets[1][1] > 0


def test_10_second_story_has_motion_variation():
    normal_flight, normal_rise = _flight_parameters(cycle=0, days=5, duration=10)
    varied_flight, varied_rise = _flight_parameters(cycle=2, days=5, duration=10)

    assert varied_flight > normal_flight
    assert varied_rise > normal_rise


def test_milestones_get_stronger_finale_and_confetti():
    ordinary = milestone_style(8)
    milestone = milestone_style(100)

    assert not ordinary.enabled
    assert milestone.enabled
    assert milestone.toss_scale > ordinary.toss_scale
    assert milestone.confetti_scale > ordinary.confetti_scale
    assert milestone.finale_scale > ordinary.finale_scale

    assert len(confetti_particles(100, 5)) > len(confetti_particles(8, 5))


def test_timeline_animates_title_days_and_finale():
    start = timeline_state(0.0, duration=5, days=7)
    intro = timeline_state(0.7, duration=5, days=7)
    finale = timeline_state(4.6, duration=5, days=7)

    assert start.title_alpha == 0
    assert intro.title_alpha > 0.99
    assert intro.days_alpha > 0.8
    assert finale.finale > 0
    assert finale.milestone_flash > 0


def test_motion_blur_only_appears_during_fast_flight():
    held = motion_blur_samples(0.1, 0, days=5, duration=5)
    fast = motion_blur_samples(0.95, 0, days=5, duration=5)

    assert held == ()
    assert len(fast) >= 1
    assert all(0 < alpha < 255 for _, alpha in fast)


def test_ball_shadow_gets_smaller_and_lighter_when_ball_is_high():
    flight, _ = _flight_parameters(cycle=0, days=5, duration=5)
    low = ball_motion(0.82 + flight * 0.05, 0, days=5, duration=5)
    high = ball_motion(0.82 + flight * 0.50, 0, days=5, duration=5)

    _, _, low_width, low_alpha = ball_shadow(low)
    _, _, high_width, high_alpha = ball_shadow(high)

    assert high_width < low_width
    assert high_alpha < low_alpha


def test_confetti_has_real_lifetime_and_gravity():
    particle = confetti_particles(7, 5)[0]
    before = confetti_state(particle, particle.birth - 0.01)
    early = confetti_state(particle, particle.birth + 0.10)
    later = confetti_state(particle, particle.birth + 0.60)
    after = confetti_state(particle, particle.birth + particle.lifetime + 0.01)

    assert before is None
    assert early is not None
    assert later is not None
    assert after is None


def test_rig_detects_silhouette_and_renders_mesh():
    source = Image.new("RGBA", (220, 260), (0, 0, 0, 0))
    draw = ImageDraw.Draw(source)
    draw.ellipse((55, 20, 165, 110), fill=(240, 180, 40, 255))
    draw.rounded_rectangle((65, 90, 155, 230), radius=35, fill=(240, 180, 40, 255))
    draw.line((70, 120, 15, 145), fill=(240, 180, 40, 255), width=22)
    draw.line((150, 120, 205, 145), fill=(240, 180, 40, 255), width=22)
    draw.ellipse((88, 55, 98, 68), fill=(20, 20, 20, 255))
    draw.ellipse((122, 55, 132, 68), fill=(20, 20, 20, 255))

    rig = JakeRig(source)
    layout = motion_layout(1.0, days=5, duration=5)
    rendered = rig.render(1.0, layout.jake)

    assert rig.landmarks.bbox[2] > rig.landmarks.bbox[0]
    assert rig.landmarks.left_hand[0] < rig.landmarks.right_hand[0]
    assert rendered.width > source.width
    assert rendered.height > source.height
    assert rendered.getbbox() is not None


def test_blink_signal_is_periodic_and_bounded():
    values = [
        motion_layout(time, days=5, duration=5).jake.blink
        for time in (1.60, 1.75, 1.90, 2.10)
    ]
    assert all(0.0 <= value <= 1.0 for value in values)
    assert max(values) > 0.9


def test_face_tracks_balls_without_animating_the_mouth():
    samples = [motion_layout(i / FPS, days=8, duration=10) for i in range(300)]
    assert all(s.jake.mouth_open == 0 for s in samples)
    assert max(s.jake.gaze[0] for s in samples) > 0.1
    assert min(s.jake.gaze[0] for s in samples) < -0.1
    assert min(s.jake.gaze[1] for s in samples) < -0.3
    for sample in samples[:270]:
        # Direction follows the actual ball positions, including higher 10s throws.
        assert sample.jake.gaze[0] == sum(b.center[0] - 360 for b in sample.balls) / 310


def test_jump_uses_ballistic_gravity_and_landing_absorption():
    takeoff = 0.85
    samples = [
        motion_layout(takeoff + dt, days=8, duration=5).jake
        for dt in (0.02, 0.12, 0.24, 0.36, 0.46)
    ]
    heights = [pose.jump_height for pose in samples]
    velocities = [pose.jump_velocity for pose in samples]

    assert heights[0] > 0
    assert heights[2] == max(heights)
    assert heights[-1] < heights[2]
    assert velocities[0] > velocities[1] > velocities[2] > velocities[3]
    landed = motion_layout(takeoff + 0.50, days=8, duration=5).jake
    assert landed.jump_height == 0
    assert landed.landing_impact > 0
    assert landed.squat > 0


def test_grounded_anticipation_release_and_settle():
    prep = motion_layout(0.68, days=8, duration=5).jake
    release = motion_layout(0.94, days=8, duration=5).jake
    settle = motion_layout(1.9, days=8, duration=5).jake
    assert prep.pose_name == "pre-throw"
    assert prep.squat > 0.9
    assert release.pose_name == "throw"
    assert release.stretch > 0.9
    assert release.heel_lift[1] > 0 and release.heel_lift[0] == 0
    assert settle.squat == settle.stretch == 0
    assert prep.hand_offsets[0][1] > release.hand_offsets[0][1]


def test_ten_second_motion_is_bounded_and_continuous():
    for days in (8, 7, 30, 100, 365):
        poses = [
            motion_layout(i / FPS, days=days, duration=10).jake for i in range(301)
        ]
        assert {p.pose_name for p in poses} == {
            "idle",
            "pre-throw",
            "throw",
            "catch",
            "celebration",
        }
        for p in poses:
            assert p.center_y == 805 and p.height_scale == 1
            assert all(0 <= h <= 3 for h in p.heel_lift)
            assert 0 <= p.squat <= 1 and 0 <= p.stretch <= 1
            assert 0 <= p.jump_height <= 31
            assert abs(p.hip_sway) <= 4
            assert all(abs(v) <= 24 for offset in p.hand_offsets for v in offset)
        for a, b in zip(poses, poses[1:]):
            assert abs(a.sway - b.sway) < 4
            assert abs(a.squat - b.squat) < 0.6
            assert (
                max(
                    abs(x - y)
                    for ah, bh in zip(a.hand_offsets, b.hand_offsets)
                    for x, y in zip(ah, bh)
                )
                < 8
            )
        assert poses[-1] == poses[-2] == poses[-3]


def test_finale_finishes_real_flights_and_holds_both_balls():
    for duration in (5, 10):
        for days in (8, 7, 100):
            last = motion_layout(duration - 0.1, days=days, duration=duration)
            earlier = motion_layout(duration - 0.2, days=days, duration=duration)
            assert last == earlier
            assert all(not b.airborne for b in last.balls)
            assert last.balls[0].center != last.balls[1].center
            assert last.jake.pose_name == "celebration"
            assert last.jake.squat == last.jake.stretch == 0
            assert last.jake.heel_lift == (0, 0)


def test_actual_asset_face_and_ground_contact_render():
    from dataclasses import replace
    from PIL import ImageChops
    from app.story.renderer import celebration_art

    rig = JakeRig(celebration_art(420), celebration=True)
    idle = motion_layout(0, days=8, duration=5).jake
    prep = motion_layout(0.72, days=8, duration=5).jake
    base = rig.render(0, idle)
    changed = rig.render(0.72, prep)
    assert rig.placement(base) == rig.placement(changed)
    assert abs(base.getbbox()[3] - changed.getbbox()[3]) <= 1
    # Lower legs move less than arms/head, in rendered pixels, not only pose values.
    diff = ImageChops.difference(base, changed).convert("RGB")
    from PIL import ImageStat

    upper = sum(ImageStat.Stat(diff.crop((0, 40, base.width, 260))).mean)
    lower = sum(ImageStat.Stat(diff.crop((0, 380, base.width, base.height))).mean)
    assert upper > lower * 2
    # الرمشة فقط مسموح تغير العين؛ شكل العين وداخلها يبقى من المرجع.
    blink = rig._with_face(replace(idle, blink=0.5))
    assert (
        ImageChops.difference(blink, rig._with_face(idle)).convert("RGB").getbbox()
        is not None
    )

    # ما نضيف pupil متحرك: gaze لا يغير أي بكسل من العين الأصلية.
    gaze = rig._with_face(replace(idle, gaze=(0.8, -0.8)))
    assert (
        ImageChops.difference(gaze, rig._with_face(idle)).convert("RGB").getbbox()
        is None
    )

    # الفم والابتسامة يبقون من الرسم الأصلي أيضًا.
    for field, value in [("smile", 0.9), ("mouth_open", 0.7)]:
        face = rig._with_face(replace(idle, **{field: value}))
        assert (
            ImageChops.difference(face, rig._with_face(idle)).convert("RGB").getbbox()
            is None
        )


def test_mesh_identity_preserves_source_orientation():
    from app.story.motion_v2 import JakePose
    from PIL import ImageStat

    source = Image.new("RGBA", (120, 120), "red")
    ImageDraw.Draw(source).rectangle((60, 0, 119, 59), fill="blue")
    rig = JakeRig(source)
    out = rig.render(0, JakePose(1, 1, 805, 0, 0, ((0, 0), (0, 0)), 0))
    assert ImageStat.Stat(out.crop((100, 40, 130, 70))).mean[2] > 240
    assert ImageStat.Stat(out.crop((40, 100, 70, 130))).mean[0] > 240
