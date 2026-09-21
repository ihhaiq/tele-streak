from __future__ import annotations

import logging
import unicodedata

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

from app.services.user_labels import user_label
from app.database.activation_repository import StreakActivationRepository
from app.database.repository import Repository
from app.keyboards.streak import start_request_keyboard
from app.services.guest_delivery import GuestDeliveryService
from app.services.message_filter import should_count
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService

logger = logging.getLogger(__name__)


def _transport_unavailable(result) -> bool:
    return bool(getattr(result, "transport_unavailable", False))


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


def is_revive_streak_query(text: str | None) -> bool:
    normalized = _normalize_text(text)
    return normalized in {
        "احياء الستريك",
        "إحياء الستريك",
        "احياء ستريك",
        "إحياء ستريك",
        "revive streak",
        "/revivestreak",
    }


def parse_task_notifications_command(text: str | None) -> bool | None:
    normalized = _normalize_text(text)
    if normalized in {
        "تعطيل الاشعارات",
        "تعطيل الإشعارات",
        "تعطيل اشعارات المهام",
        "تعطيل إشعارات المهام",
        "كتم الاشعارات",
        "كتم الإشعارات",
        "كتم اشعارات المهام",
        "كتم إشعارات المهام",
        "/mutetasks",
        "/tasknotifyoff",
        "mute task notifications",
    }:
        return False
    if normalized in {
        "تفعيل الاشعارات",
        "تفعيل الإشعارات",
        "تفعيل اشعارات المهام",
        "تفعيل إشعارات المهام",
        "تشغيل الاشعارات",
        "تشغيل الإشعارات",
        "تشغيل اشعارات المهام",
        "تشغيل إشعارات المهام",
        "/unmutetasks",
        "/tasknotifyon",
        "enable task notifications",
    }:
        return True
    return None


def parse_add_streak_days(text: str | None) -> int | None:
    normalized = _normalize_text(text)
    prefixes = ("اضف ستريك", "أضف ستريك", "add streak", "/addstreak")
    for prefix in prefixes:
        if normalized == prefix:
            return 1
        if normalized.startswith(prefix + " "):
            raw_days = normalized[len(prefix):].strip()
            try:
                days = int(raw_days)
            except ValueError:
                return 0
            return days if 1 <= days <= 10_000 else 0
    return None


def build_router(
    streaks: StreakService,
    stickers: StickerService,
    repository: Repository,
    activations: StreakActivationRepository,
    guests: GuestDeliveryService,
    adventures=None,
) -> Router:
    router = Router(name="business_messages")

    @router.business_message()
    async def on_business_message(message: Message) -> None:
        if adventures and await adventures.handle_music_upload(message):
            return
        incoming_connection_id = message.business_connection_id
        connection_id = (
            await repository.resolve_active_connection_id(incoming_connection_id)
            if incoming_connection_id
            else None
        ) or incoming_connection_id
        if (
            incoming_connection_id
            and connection_id
            and incoming_connection_id != connection_id
        ):
            logger.info(
                "BUSINESS_CONNECTION_REBOUND old=%s new=%s chat=%s",
                incoming_connection_id,
                connection_id,
                message.chat.id,
            )

        if is_streak_query(message.text):
            logger.info(
                "STREAK_COMMAND connection=%s chat=%s message=%s",
                connection_id,
                message.chat.id,
                message.message_id,
            )
            status = await streaks.get_status(message, connection_id)
            if status is not None and connection_id:
                record = await repository.get_streak(connection_id, message.chat.id)
                active = await activations.is_active(connection_id, message.chat.id)
                if not active or record is None:
                    await stickers.send_notice_text(
                        connection_id=connection_id,
                        chat_id=message.chat.id,
                        text=(
                            "🔥 لا يوجد ستريك مفعّل في هذه المحادثة بعد. "
                            "اكتب «بدأ ستريك» لبدئه، أو وافق على طلب صديقك من خاص البوت."
                        ),
                    )
                    return

                if status.current > 0:
                    sent = await guests.summon(
                        event="success",
                        connection_id=connection_id,
                        chat_id=message.chat.id,
                        reply_to_message_id=message.message_id,
                    )
                    if _transport_unavailable(sent):
                        return
                    if not sent:
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

                sent = await guests.summon(
                    event="status",
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    reply_to_message_id=message.message_id,
                )
                if _transport_unavailable(sent):
                    return
                if not sent:
                    timezone_name = await repository.get_connection_timezone(connection_id)
                    owner_user_id = await repository.get_owner_id(connection_id)
                    if owner_user_id is None:
                        return
                    profile = (await adventures.snapshot(connection_id, message.chat.id))[0] if adventures else None
                    await stickers.send_status(
                        connection_id=connection_id,
                        owner_user_id=owner_user_id,
                        chat_id=message.chat.id,
                        current=status.current,
                        longest=status.longest,
                        completed_days=status.completed_days,
                        break_count=status.break_count,
                        freeze_count=status.freeze_count,
                        last_completed_day=status.last_completed_day,
                        streak_mode=record.streak_mode,
                        timezone_name=timezone_name,
                        adventure_profile=profile,
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

        add_days = parse_add_streak_days(message.text)
        if add_days is not None:
            if not connection_id or message.from_user is None:
                return
            owner_id = await streaks.get_owner_id(message, connection_id)
            if owner_id is None or message.from_user.id != owner_id:
                return
            if add_days <= 0:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="استخدم: «اضف ستريك» لإضافة يوم، أو «اضف ستريك 5» لإضافة 5 أيام.",
                )
                return

            active = await activations.is_active(connection_id, message.chat.id)
            record = await repository.get_streak(connection_id, message.chat.id)
            if not active or record is None or not record.is_enabled:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="🔥 ماكو ستريك مفعّل بهذه المحادثة حتى أرفعه. ابدأ الستريك أولًا.",
                )
                return

            updated = await repository.add_streak_days(
                connection_id=connection_id,
                chat_id=message.chat.id,
                days=add_days,
            )
            if updated is None:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="تعذر تعديل الستريك حاليًا.",
                )
                return

            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text=(
                    f"🔥 تمت إضافة {add_days} للستريك. "
                    f"الستريك الآن: {updated.current_streak} يوم."
                ),
            )
            logger.info(
                "STREAK_MANUAL_ADD connection=%s chat=%s owner=%s added=%s current=%s",
                connection_id,
                message.chat.id,
                owner_id,
                add_days,
                updated.current_streak,
            )
            return

        task_notifications = parse_task_notifications_command(message.text)
        if task_notifications is not None:
            if not connection_id or message.from_user is None:
                return
            owner_id = await streaks.get_owner_id(message, connection_id)
            if owner_id is None or message.from_user.id != owner_id:
                return
            updated = await repository.set_task_notifications(
                owner_id,
                message.chat.id,
                task_notifications,
            )
            if updated is None:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="🔥 ماكو ستريك محفوظ بهاي المحادثة حتى أغيّر إشعارات المهام.",
                )
                return
            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text=(
                    "🔔 فعلت إشعارات اكتمال المهام بهاي المحادثة."
                    if updated
                    else (
                        "🔕 عطلت إشعارات اكتمال المهام بهاي المحادثة. "
                        "المهام تبقى تتحدث بقائمة المهام."
                    )
                ),
            )
            logger.info(
                "STREAK_TASK_NOTIFICATIONS connection=%s chat=%s enabled=%s",
                connection_id,
                message.chat.id,
                updated,
            )
            return

        if is_revive_streak_query(message.text):
            if not connection_id or message.from_user is None:
                return
            owner_id = await streaks.get_owner_id(message, connection_id)
            if owner_id is None:
                return
            record = await repository.get_streak(connection_id, message.chat.id)
            allowed_users = {owner_id}
            if record is not None and record.peer_user_id is not None:
                allowed_users.add(record.peer_user_id)
            if message.from_user.id not in allowed_users:
                return

            sent = await guests.summon(
                event="revive",
                connection_id=connection_id,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                ttl_seconds=90,
            )
            if _transport_unavailable(sent):
                return
            if not sent:
                await stickers.send_notice_text(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    text="تعذر استدعاء وضع الضيف لطلب الإحياء حاليًا.",
                )
            logger.info(
                "STREAK_REVIVE_REQUESTED connection=%s chat=%s sender=%s",
                connection_id,
                message.chat.id,
                message.from_user.id,
            )
            return

        if not should_count(message) or not connection_id or message.from_user is None:
            return

        owner_id = await streaks.get_owner_id(message, connection_id)
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
            await streaks.start_by_owner(message, connection_id)
            peer_name = await user_label(message.bot, message.chat.id, "الطرف الثاني", repository)
            await stickers.send_notice_text(
                connection_id=connection_id,
                chat_id=message.chat.id,
                text=f"🔥 بدأ الستريك. ✅ أكمل اليوم: {message.from_user.full_name}\n⏳ بانتظار: {peer_name}",
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
                        f"وسيتم احتساب رسالة {peer_name} الحالية ثم ينتظر البوت رسالتك."
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

        completion = await streaks.register_message(message, connection_id)
        if not completion.completed or completion.pose is None:
            if adventures is not None:
                await adventures.after_activity(connection_id, message.chat.id, completion)
            return

        sent = await guests.summon(
            event="success",
            connection_id=connection_id,
            chat_id=message.chat.id,
            reply_to_message_id=message.message_id,
        )
        if _transport_unavailable(sent):
            return
        if not sent:
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

        if adventures is not None:
            await adventures.after_activity(connection_id, message.chat.id, completion)

    return router
