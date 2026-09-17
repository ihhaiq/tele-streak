from PIL import Image, ImageSequence

from app.services.broken_animation import BrokenAnimationService
from app.services.streak_messages import build_broken_notice_rich_message


def test_broken_gif_is_real_two_frame_one_second_animation(tmp_path):
    source = tmp_path / "broken.webp"
    destination = tmp_path / "broken.gif"
    Image.new("RGBA", (32, 32), (255, 80, 80, 255)).save(source, format="WEBP")

    BrokenAnimationService.render_one_second_gif(source, destination)

    with Image.open(destination) as animation:
        assert animation.format == "GIF"
        frames = list(ImageSequence.Iterator(animation))
        durations = [frame.info.get("duration", 0) for frame in frames]
        assert animation.n_frames == 2
        assert len(frames) == 2
        assert durations == [500, 500]
        assert sum(durations) == 1000


def test_broken_rich_message_layout_has_h1_divider_then_animation():
    rich = build_broken_notice_rich_message("animation-file-id")

    assert rich.is_rtl is True
    assert rich.blocks is not None
    assert rich.blocks[0].__class__.__name__ == "InputRichBlockSectionHeading"
    assert rich.blocks[0].size == 1
    assert rich.blocks[0].text == "💔 الستريك مات"
    assert rich.blocks[1].__class__.__name__ == "InputRichBlockDivider"
    assert rich.blocks[2].__class__.__name__ == "InputRichBlockAnimation"
    assert rich.blocks[2].animation.media == "animation-file-id"
