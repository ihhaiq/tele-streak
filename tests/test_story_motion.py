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
