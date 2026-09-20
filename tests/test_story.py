import json
import shutil
import subprocess
import wave

import pytest
from PIL import Image, ImageChops, features

from app.story.renderer import (
    StoryRenderer,
    avatar_ball,
    celebration_art,
    clean_name,
    soundtrack,
)


def test_avatar_handles_missing_photo_long_arabic_and_control_characters(tmp_path):
    result = avatar_ball("حسين " * 25, None, "#ffd56b")
    assert result.size == (192, 192) and result.getbbox()
    assert "\n" not in clean_name("حسين\nTest")
    broken = tmp_path / "bad.jpg"
    broken.write_bytes(b"bad")
    assert avatar_ball("A", broken, "#ffd56b").getbbox()


def test_celebration_has_safe_margins_and_full_body():
    image = celebration_art()
    box = image.getbbox()
    assert image.size == (512, 512)
    assert box[0] >= 10 and box[1] >= 10 and box[2] <= 502 and box[3] <= 502
    # القدمين ضمن الربع الأخير؛ ما يرجع القص القديم.
    assert image.crop((0, 400, 512, 512)).getbbox()


def test_built_in_music_is_audible_and_exact_duration(tmp_path):
    path = tmp_path / "music.wav"
    soundtrack(path, 5)
    with wave.open(str(path), "rb") as music:
        assert music.getnframes() / music.getframerate() == 5
        assert len(set(music.readframes(5000))) > 20


@pytest.mark.skipif(
    not shutil.which("ffmpeg")
    or not shutil.which("ffprobe")
    or not features.check_feature("raqm"),
    reason="FFmpeg and Arabic shaping are required for video integration",
)
@pytest.mark.parametrize("duration", [5, 10])
def test_real_story_has_motion_arabic_h264_aac_and_portrait_dimensions(
    tmp_path, duration
):
    avatar = tmp_path / "profile.jpg"
    Image.new("RGB", (300, 240), "#41bca9").save(avatar)
    output = StoryRenderer().render(
        tmp_path,
        days=1234,
        names=("حسين", "صديق"),
        photos=(avatar, None),
        duration=duration,
    )
    meta = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(output),
            ]
        )
    )
    video = next(s for s in meta["streams"] if s["codec_type"] == "video")
    audio = next(s for s in meta["streams"] if s["codec_type"] == "audio")
    assert (video["codec_name"], video["width"], video["height"]) == ("h264", 720, 1280)
    assert audio["codec_name"] == "aac"
    assert abs(float(meta["format"]["duration"]) - duration) < 0.15
    with (
        Image.open(tmp_path / "frames/0000.jpg") as first,
        Image.open(tmp_path / "frames/0012.jpg") as second,
    ):
        assert ImageChops.difference(first, second).getbbox() is not None
    assert output.stat().st_size < 10_000_000


def test_story_rejects_bad_duration_and_missing_song(tmp_path):
    with pytest.raises(ValueError):
        StoryRenderer().render(tmp_path, days=1, names=("A", "B"), duration=20)
    if shutil.which("ffmpeg") and features.check_feature("raqm"):
        with pytest.raises(FileNotFoundError):
            StoryRenderer(tmp_path / "missing.mp3").render(
                tmp_path, days=1, names=("A", "B")
            )
