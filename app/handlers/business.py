from __future__ import annotations

import logging
import unicodedata

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message, ReplyParameters

from app.database.activation_repository import StreakActivationRepository
from app.database.repository import Repository
from app.keyboards.streak import start_request_keyboard
from app.services.message_filter import should_count
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService

logger = logging.getLogger(__name__)


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text).strip().lower()
    return "".join(
        char for char in normalized
        if char != "ـ" and not unicodedata.combining(char)
    )


def is_streak_query(text: str | None) -> bool:
    normalized = _normalize_text(text)
    first = normalized.split(maxsplit=1)[0] if normalized else ""
    first = first.split("@", 1)[0]
    return first in {"ستريك", "/ستريك", "streak", "/streak"}


def is_start_streak_query(text: str | None) -> bool:
    normalized = _normalize_text(text)
    return normalized in {
        "بدأ ستريك",
        "بدا ستريك",
        "ابدأ ستريك",
        "بدء ستريك",
        "start streak",
        "/startstreak",
    }


def build_router(
    streaks: StreakService,
    stickers: StickerService,
    repository: Repository,
    activations: StreakActivationRepository,
) -> Router:
    router = Router(name="business_messages")

    @router.business_message()
    async def on_business_message(message: Message) -> None:
        connection_id = message.business_connection_id

        if is_streak_query(message.text):
            logger.info(
                "STREAK_COMMAND connection=%s chat=%s message=%s",
                connection_id,
                message.chat.id,
                message.message_id,
            )
            status = await streaks.get_status(message)
            if status is not None and connection_id:
                record = await repository.get_streak(connection_id, message.chat.id)
                active = await activations.is_active(connection_id, message.chat.id)
                if not active or record is None:
                    await stickers.send_notice_text(
                        connection_id=connection_id,
                        chat_id=message.chat.id,
                        text=(
                            "🔥 لا يوجد ستريك مفعّل في هذه المحادثة بعد. "
                            "اكتب «بدأ ستريك» لبدئه، أو وافق على طلب الطرف الثاني من خاص البوت."
                        ),
                    )
                    return

                if status.current > 0:
                    pose = record.last_pose or streaks.poses.choose(status.current, None).id
                    try:
                        await stickers.send_success(
                            connection_id=connection_id,
                            chat_id=message.chat.id,
                            pose=pose,
                            days=status.current,
                        )
                    except Exception:
                        logger.exception(
                            "STREAK_STATUS_STICKER_FAILED connection=%s chat=%s days=%s",
                            connection_id,
                            message.chat.id,
                            status.current,
                        )

                me = await message.bot.get_me()
                if me.username and bool(me.supports_guest_queries):
                    token = await repository.create_guest_streak_request(
                        connection_id,
                        message.chat.id,
                    )
                    if token is None:
                        logger.info(
                            "STREAK_GUEST_COOLDOWN connection=%s chat=%s",
                            connection_id,
                            message.chat.id,
                        )
                        return
                    try:
                        summon = await message.bot.send_message(
                            chat_id=message.chat.id,
                            business_connection_id=connection_id,
                            text=f"@{me.username} streak:{token}",
                            disable_notification=True,
                            reply_parameters=ReplyParameters(
                                message_id=message.message_id,
                            ),
                        )
                    except TelegramBadRequest as error:
                        await repository.finish_guest_streak_request(token)
                        logger.warning(
                            "STREAK_GUEST_INVOKE_REJECTED connection=%s chat=%s error=%s",
                            connection_id,
                            message.chat.id,
                            error,
                        )
                    else:
                        await repository.set_guest_streak_summon_message(
                            token,
                            summon.message_id,
                        )
                        logger.info(
                            "STREAK_GUEST_INVOKE_SENT connection=%s chat=%s message=%s",
                            connection_id,
                            message.chat.id,
                            summon.message_id,
                        )
                        return

                logger.warning(
                    "STREAK_GUEST_UNAVAILABLE connection=%s chat=%s supports_guest=%s",
                    connection_id,
                    message.chat.id,
                    bool(me.supports_guest_queries),
                )
                timezone_name = await repository.get_connection_timezone(connection_id)
                await stickers.send_status(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    current=status.current,
                    longest=status.longest,
                    completed_days=status.completed_days,
                    break_count=status.break_count,
                    freeze_count=status.freeze_count,
                    last_completed_day=status.last_completed_day,
                    timezone_name=timezone_name,
                )
            elif connection_id:
                logger.warning(
                    "STREAK_COMMAND_STATUS_UNAVAILABLE connection=%s chat=%s",
                    connection_id,
                    message.chat.id,
                )
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="تعذر قراءة الستريك مؤقتًا. تأكد أن اتصال الأعمال مفعّل ثم حاول مجددًا.",
                )
            return

        if not should_count(message) or not connection_id or message.from_user is None:
            return

        owner_id = await streaks.get_owner_id(message)
        if owner_id is None:
            return

        sender_id = message.from_user.id
        record = await repository.get_streak(connection_id, message.chat.id)
        active = await activations.is_active(connection_id, message.chat.id)

        if is_start_streak_query(message.text) and sender_id == owner_id:
            if active and record is not None and record.is_enabled:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="🔥 الستريك مفعّل أصلًا في هذه المحادثة.",
                )
                return

            await activations.clear_chat(connection_id, message.chat.id)
            await streaks.start_by_owner(message)
            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text="🔥 بدأ الستريك. تم احتساب رسالتك، وبانتظار رسالة من الطرف الثاني اليوم.",
            )
            logger.info(
                "STREAK_STARTED_BY_OWNER connection=%s chat=%s",
                connection_id,
                message.chat.id,
            )
            return

        if not active:
            if sender_id == owner_id:
                return

            owner_target = await activations.get_owner_target(connection_id)
            if owner_target is None:
                return
            _, owner_chat_id = owner_target
            token = await activations.create_request(
                connection_id=connection_id,
                chat_id=message.chat.id,
                peer_user_id=sender_id,
                source_message_id=message.message_id,
            )
            if token is None:
                return

            peer_name = message.from_user.full_name
            peer_username = (
                f" (@{message.from_user.username})"
                if message.from_user.username
                else ""
            )
            try:
                await message.bot.send_message(
                    chat_id=owner_chat_id,
                    text=(
                        "🔥 طلب بدء ستريك\n\n"
                        f"{peer_name}{peer_username} أرسل رسالة في محادثتك.\n"
                        "الستريك لن يبدأ تلقائيًا. اضغط الزر إذا تريد تفعيله؛ "
                        "وسيتم احتساب رسالة الطرف الثاني الحالية ثم ينتظر البوت رسالتك."
                    ),
                    reply_markup=start_request_keyboard(token),
                )
            except (TelegramBadRequest, TelegramForbiddenError) as error:
                await activations.clear_chat(connection_id, message.chat.id)
                logger.warning(
                    "STREAK_START_REQUEST_SEND_FAILED connection=%s chat=%s error=%s",
                    connection_id,
                    message.chat.id,
                    error,
                )
            else:
                logger.info(
                    "STREAK_START_REQUEST_SENT connection=%s chat=%s owner=%s",
                    connection_id,
                    message.chat.id,
                    owner_id,
                )
            return

        if record is not None and not record.is_enabled:
            return

        completion = await streaks.register_message(message)
        if not completion.completed or completion.pose is None:
            return

        try:
            await stickers.send_success(
                connection_id=connection_id,
                chat_id=message.chat.id,
                pose=completion.pose,
                days=completion.days,
            )
        except Exception:
            logger.exception(
                "STREAK_STICKER_SEND_FAILED connection=%s chat=%s days=%s",
                connection_id,
                message.chat.id,
                completion.days,
            )

    return router
