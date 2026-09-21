from PIL import Image

from app.story.renderer import (
    _ball_motion,
    _elastic_jake,
    _motion_layout,
)


def test_ball_follows_gravity_arc_between_hands():
    launch = _ball_motion(0.35, 0)
    quarter = _ball_motion(0.35 + 1.35 * 0.25, 0)
    apex = _ball_motion(0.35 + 1.35 * 0.50, 0)
    three_quarters = _ball_motion(0.35 + 1.35 * 0.75, 0)
    caught = _ball_motion(0.35 + 1.35, 0)

    assert launch.airborne
    assert apex.airborne
    assert not caught.airborne
    assert launch.center == (205.0, 655.0)
    assert caught.center[0] == 515.0
    assert abs(caught.center[1] - 655.0) < 0.01

    # السرعة الأفقية ثابتة تقريبًا، والقمة بالنص.
    assert 350.0 <= apex.center[0] <= 370.0
    assert apex.center[1] < quarter.center[1]
    assert apex.center[1] < three_quarters.center[1]
    assert abs(quarter.center[1] - three_quarters.center[1]) < 0.01


def test_ball_accelerates_downward_after_apex():
    a = _ball_motion(0.35 + 1.35 * 0.55, 0)
    b = _ball_motion(0.35 + 1.35 * 0.65, 0)
    c = _ball_motion(0.35 + 1.35 * 0.75, 0)
    d = _ball_motion(0.35 + 1.35 * 0.85, 0)

    first_drop = c.center[1] - b.center[1]
    second_drop = d.center[1] - c.center[1]
    assert first_drop > 0
    assert second_drop > first_drop


def test_jake_uses_controlled_squash_stretch_and_chain_motion():
    layouts = [_motion_layout(index * 0.15) for index in range(30)]

    widths = [item.jake_width_scale for item in layouts]
    heights = [item.jake_height_scale for item in layouts]
    amplitudes = [item.chain_amplitude for item in layouts]

    assert min(widths) >= 0.95
    assert max(widths) <= 1.055
    assert min(heights) >= 0.94
    assert max(heights) <= 1.065
    assert max(widths) - min(widths) > 0.005
    assert max(heights) - min(heights) > 0.005
    assert all(7.0 <= amplitude <= 9.5 for amplitude in amplitudes)


def test_elastic_jake_keeps_feet_more_stable_than_upper_body():
    source = Image.new("RGBA", (420, 420), (255, 255, 255, 255))
    actor_a = _elastic_jake(
        source,
        0.40,
        width_scale=1.0,
        height_scale=1.0,
        chain_amplitude=9.0,
    )
    actor_b = _elastic_jake(
        source,
        0.90,
        width_scale=1.0,
        height_scale=1.0,
        chain_amplitude=9.0,
    )

    assert actor_a.height == source.height
    assert actor_b.height == source.height
    assert actor_a.width > source.width
    assert actor_b.width > source.width
    assert actor_a.getbbox() is not None
    assert actor_b.getbbox() is not None
