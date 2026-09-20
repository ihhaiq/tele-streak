from __future__ import annotations

from aiogram.types import Message


def should_count(message: Message) -> bool:
    # This MVP only tracks private Business chats.
    if message.chat.type != "private":
        return False

    # Ignore anything the connected bot itself sent on behalf of the business account.
    if getattr(message, "sender_business_bot", None) is not None:
        return False

    # Greeting/away/scheduled automatic business messages should not create activity.
    if bool(getattr(message, "is_from_offline", False)):
        return False

    if message.from_user and message.from_user.is_bot:
        return False

    # Service messages do not contain normal user content. Count common human message types.
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
    if mode == "media":
        return bool(getattr(message, "photo", None) or getattr(message, "video", None))
    if mode == "voice":
        return bool(getattr(message, "voice", None))
    return True
