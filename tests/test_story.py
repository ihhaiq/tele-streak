import json
import shutil
import subprocess
import wave
from fractions import Fraction

import pytest
from PIL import Image, ImageChops, features

from app.story.renderer import (
    StoryRenderer,
    avatar_ball,
    celebration_art,
    clean_name,
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



@pytest.mark.skipif(
    not features.check_feature("raqm"),
    reason="Arabic shaping is required for the still story",
)
def test_static_story_matches_business_story_photo_requirements(tmp_path):
    avatar = tmp_path / "profile.jpg"
    Image.new("RGB", (300, 240), "#41bca9").save(avatar)
    output = StoryRenderer().render_image(
        tmp_path,
        days=77,
        names=("حسين", "صديق"),
        photos=(avatar, None),
    )
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.size == (1080, 1920)
        assert image.getbbox() is not None
    assert output.stat().st_size < 10_000_000


@pytest.mark.skipif(
    not shutil.which("ffmpeg")
    or not shutil.which("ffprobe")
    or not features.check_feature("raqm"),
    reason="FFmpeg and Arabic shaping are required for video integration",
)
@pytest.mark.parametrize("duration", [5, 10])
def test_real_story_has_motion_arabic_h265_aac_and_portrait_dimensions(
    tmp_path, duration
):
    avatar = tmp_path / "profile.jpg"
    music = tmp_path / "youtube-clip.wav"
    with wave.open(str(music), "wb") as output_music:
        output_music.setnchannels(1)
        output_music.setsampwidth(2)
        output_music.setframerate(22050)
        output_music.writeframes(b"\x00\x00" * 22050 * (duration + 1))
    Image.new("RGB", (300, 240), "#41bca9").save(avatar)
    output = StoryRenderer().render(
        tmp_path,
        days=1234,
        names=("حسين", "صديق"),
        photos=(avatar, None),
        duration=duration,
        music_path=music,
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
    assert (video["codec_name"], video["width"], video["height"]) == ("hevc", 720, 1280)
    frame_rate = Fraction(video["r_frame_rate"])
    keyframes = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-skip_frame",
            "nokey",
            "-show_entries",
            "frame=pts_time",
            "-of",
            "csv=p=0",
            str(output),
        ],
        text=True,
    ).strip().splitlines()
    assert frame_rate == Fraction(30, 1)
    assert len(keyframes) >= duration
    assert audio["codec_name"] == "aac"
    assert abs(float(meta["format"]["duration"]) - duration) < 0.15
    with (
        Image.open(tmp_path / "frames/0000.jpg") as first,
        Image.open(tmp_path / "frames/0012.jpg") as second,
    ):
        assert ImageChops.difference(first, second).getbbox() is not None
    assert output.stat().st_size < 30_000_000


def test_story_rejects_bad_duration_and_supports_silent_video(tmp_path):
    with pytest.raises(ValueError):
        StoryRenderer().render(tmp_path, days=1, names=("A", "B"), duration=20)
    # رفع الأغنية اختياري؛ الفيديو الصامت هو السلوك الطبيعي بدون ملف مرفوع.
