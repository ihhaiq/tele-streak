from __future__ import annotations

from aiogram.types import Message


def should_count(message: Message, mode: str = "message") -> bool:
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

    if mode == "media":
        return bool(message.photo or message.video)
    if mode == "voice":
        return bool(message.voice)

    # الوضع الافتراضي: أي رسالة بشرية معتادة تحتسب للستريك.
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
