from __future__ import annotations

from aiogram.types import Message

from app.streak_modes import MODE_MESSAGE, MODE_PHOTO_VIDEO, MODE_VOICE


def should_count(message: Message) -> bool:
    # الستريك يعمل فقط داخل محادثات Business الخاصة.
    if message.chat.type != "private":
        return False

    # تجاهل رسائل البوت نفسه.
    if getattr(message, "sender_business_bot", None) is not None:
        return False

    # رسائل الترحيب والغياب والرسائل التلقائية ما تنحسب.
    if bool(getattr(message, "is_from_offline", False)):
        return False

    if message.from_user and message.from_user.is_bot:
        return False

    # نحسب فقط الرسائل والمحتوى الطبيعي من المستخدم.
    return any(
        (
            message.text,
            message.photo,
            message.video,
            message.voice,
            message.video_note,
            message.sticker,
            message.animation,
            message.document,
            message.audio,
            message.location,
            message.contact,
        )
    )


def matches_streak_mode(message: Message, mode: str) -> bool:
    """Return whether a countable message satisfies the chat's streak mode."""
    if mode == MODE_MESSAGE:
        return bool(message.text)
    if mode == MODE_PHOTO_VIDEO:
        return bool(message.photo or message.video)
    if mode == MODE_VOICE:
        return message.voice is not None
    return False
