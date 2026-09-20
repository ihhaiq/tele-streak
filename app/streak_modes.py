from __future__ import annotations

MODE_MESSAGE = "message"
MODE_PHOTO_VIDEO = "photo_video"
MODE_VOICE = "voice"

STREAK_MODES = (MODE_MESSAGE, MODE_PHOTO_VIDEO, MODE_VOICE)

STREAK_MODE_LABELS = {
    MODE_MESSAGE: "رسالة",
    MODE_PHOTO_VIDEO: "صورة / فيديو",
    MODE_VOICE: "بصمة صوتية",
}


def streak_mode_label(mode: str) -> str:
    return STREAK_MODE_LABELS.get(mode, STREAK_MODE_LABELS[MODE_MESSAGE])
