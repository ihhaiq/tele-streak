from app.story.renderer import WIDTH, _motion_layout


def test_story_motion_enters_once_then_settles():
    start = _motion_layout(0.0)
    settled = _motion_layout(1.0)

    assert 0.93 <= start.jake_scale <= 0.95
    assert 0.99 <= settled.jake_scale <= 1.01
    assert start.ball_centers[0][0] < 0
    assert start.ball_centers[1][0] > WIDTH
    assert 130 <= settled.ball_centers[0][0] <= 200
    assert 520 <= settled.ball_centers[1][0] <= 590
    assert settled.ball_scales[0] == 1.0
    assert settled.ball_scales[1] == 1.0


def test_settled_story_motion_stays_subtle():
    layouts = [_motion_layout(1.0 + index * 0.25) for index in range(12)]

    jake_scales = [layout.jake_scale for layout in layouts]
    jake_y = [layout.jake_y for layout in layouts]
    left_x = [layout.ball_centers[0][0] for layout in layouts]
    left_y = [layout.ball_centers[0][1] for layout in layouts]
    right_x = [layout.ball_centers[1][0] for layout in layouts]
    right_y = [layout.ball_centers[1][1] for layout in layouts]

    assert max(jake_scales) - min(jake_scales) < 0.01
    assert max(jake_y) - min(jake_y) <= 6.1
    assert max(left_x) - min(left_x) <= 4.1
    assert max(right_x) - min(right_x) <= 4.1
    assert max(left_y) - min(left_y) <= 8.1
    assert max(right_y) - min(right_y) <= 8.1
