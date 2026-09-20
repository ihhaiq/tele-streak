from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    Message,
)

from app.adventures.views import navigation, page_text, rich_page
from app.services.rich_status import (
    build_streak_fallback_text,
    build_streak_rich_message,
)

logger = logging.getLogger(__name__)


def story_menu(owner, chat):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="٥ ثواني 🎬", callback_data=f"adv:video5:{owner}:{chat}"
                ),
                InlineKeyboardButton(
                    text="١٠ ثواني 🎬", callback_data=f"adv:video10:{owner}:{chat}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="رجوع", callback_data=f"adv:tasks:{owner}:{chat}"
                )
            ],
        ]
    )


async def edit_page(callback, bot, rich, text, keyboard):
    kwargs = (
        {"inline_message_id": callback.inline_message_id}
        if callback.inline_message_id
        else {
            "chat_id": callback.message.chat.id,
            "message_id": callback.message.message_id,
            "business_connection_id": callback.message.business_connection_id,
        }
    )
    try:
        await bot.edit_message_text(**kwargs, rich_message=rich, reply_markup=keyboard)
    except TelegramBadRequest as error:
        if "message is not modified" in str(error).lower():
            return True
        try:
            await bot.edit_message_text(**kwargs, text=text, reply_markup=keyboard)
        except TelegramBadRequest:
            # أزرار ملصق الاحتفال تحتاج رسالة جديدة، لأن الملصق ما يتحول إلى نص.
            return False
    return True


def build_router(repository, adventures) -> Router:
    router = Router(name="adventures")

    @router.callback_query(F.data.startswith("adv:"))
    async def on_adventure(callback: CallbackQuery, bot: Bot):
        try:
            _, action, raw_owner, raw_chat = (callback.data or "").split(":")
            owner, chat = int(raw_owner), int(raw_chat)
        except (ValueError, TypeError):
            await callback.answer()
            return
        if action not in {
            "tasks",
            "compare",
            "badges",
            "story",
            "video5",
            "video10",
            "status",
        }:
            await callback.answer()
            return
        record = await repository.get_owner_streak(owner, chat)
        if record is None or callback.from_user.id not in {
            owner,
            record.peer_user_id or record.chat_id,
        }:
            await callback.answer("هاي مغامرة خاصة بطرفي الستريك 🫠", show_alert=True)
            return
        if not callback.inline_message_id and not isinstance(callback.message, Message):
            await callback.answer()
            return
        if action.startswith("video"):
            if not record.is_enabled:
                await callback.answer("فعّلوا الستريك أولًا.", show_alert=True)
                return
            await callback.answer("Jake دا يجهز الفيديو 🎬")
            try:
                error = await adventures.send_story(record, owner, int(action[5:]))
            except Exception:
                logger.exception("STORY_RENDER_OR_SEND_FAILED")
                error = "تعذر تجهيز الستوري هالمرة، جرب بعد شوي 🎬"
            if error:
                await bot.send_message(
                    chat_id=record.chat_id,
                    business_connection_id=record.business_connection_id,
                    text=error,
                )
            return
        profile, state = await adventures.snapshot(record.business_connection_id, chat)
        if action == "status":
            values = dict(
                current=record.current_streak,
                longest=record.longest_streak,
                completed_days=record.completed_days,
                break_count=record.break_count,
                freeze_count=record.freeze_count,
                last_completed_day=record.last_completed_day,
                streak_mode=record.streak_mode,
                timezone_name=await repository.get_connection_timezone(
                    record.business_connection_id
                ),
                adventure_profile=profile,
            )
            rich = build_streak_rich_message(
                **values, owner_user_id=owner, chat_id=chat
            )
            text = build_streak_fallback_text(**values)
            keyboard = navigation(owner, chat)
        elif action == "story":
            text = "🎬 مشاركة ستوري\nاختار المدة، وJake يلعب بكرتين بيهن صوركم وأسماءكم، ويا موسيقى 🎵"
            rich = InputRichMessage(
                html="<h1>🎬 مشاركة ستوري</h1><p>اختار المدة، وJake يلعب بكرتين بيهن صوركم وأسماءكم، ويا موسيقى 🎵</p>",
                is_rtl=True,
            )
            keyboard = story_menu(owner, chat)
        else:
            text = page_text(profile, state, action)
            rich = rich_page(profile, state, action, owner, chat)
            keyboard = navigation(owner, chat)
        await callback.answer()
        if not await edit_page(callback, bot, rich, text, keyboard):
            destination = dict(
                chat_id=record.chat_id,
                business_connection_id=record.business_connection_id,
            )
            try:
                await bot.send_rich_message(
                    **destination, rich_message=rich, reply_markup=keyboard
                )
            except TelegramBadRequest:
                await bot.send_message(**destination, text=text, reply_markup=keyboard)

    return router
