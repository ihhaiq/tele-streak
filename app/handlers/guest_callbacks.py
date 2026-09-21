from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.revive_request_repository import ReviveApprovalState, ReviveRequestRepository
from app.database.repository import Repository
from app.services.rich_status import protection_text
from app.services.user_labels import user_label


def _approval_text(state: ReviveApprovalState, owner_name: str = "الطرف الأول", peer_name: str = "الطرف الثاني") -> str:
    owner = "✅" if state.owner_approved else "⏳"
    peer = "✅" if state.peer_approved else "⏳"
    return (
        "🧊 طلب إحياء الستريك\n\n"
        f"{owner_name}: {owner}\n"
        f"{peer_name}: {peer}\n\n"
        "لا يتم إحياء الستريك إلا بعد موافقة الطرفين."
    )


def _approval_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ موافقة",
                    callback_data=f"streak_revive:approve:{token}",
                )
            ]
        ]
    )


def build_router(
    repository: Repository,
    revive_requests: ReviveRequestRepository,
    adventures=None,
) -> Router:
    router = Router(name="guest_callbacks")

    @router.callback_query(F.data.startswith("story_publish:"))
    async def publish_story(callback: CallbackQuery, bot: Bot) -> None:
        if adventures is None:
            await callback.answer(
                "نشر الستوري غير متاح حاليًا.",
                show_alert=True,
            )
            return

        token = (callback.data or "").split(":", 1)[-1]
        with suppress(TelegramBadRequest):
            await callback.answer("جاري نشر الستوري 🚀")
        result = await adventures.publish_story(token, callback.from_user.id)

        if result.status == "published":
            final_text = "✅ تم نشر الستوري على حساب الأعمال."
            if callback.inline_message_id:
                with suppress(TelegramBadRequest):
                    await bot.edit_message_caption(
                        inline_message_id=callback.inline_message_id,
                        caption=final_text,
                        reply_markup=None,
                    )
            elif isinstance(callback.message, Message):
                with suppress(TelegramBadRequest):
                    await bot.edit_message_caption(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        business_connection_id=callback.message.business_connection_id,
                        caption=final_text,
                        reply_markup=None,
                    )
            return

        messages = {
            "expired": "انتهت صلاحية المعاينة. سوي معاينة جديدة.",
            "owner_only": "نشر الستوري متاح فقط لصاحب حساب الـBusiness.",
            "unauthorized": "ما عندك صلاحية لنشر هاي الستوري.",
            "publishing": "الستوري قيد النشر حاليًا.",
            "permission": (
                "فعّل صلاحية إدارة الستوريات للبوت من إعدادات Telegram Business."
            ),
            "failed": "Telegram رفض نشر الستوري أو صار خطأ. جرب مرة ثانية.",
        }
        error_text = messages.get(result.status, "تعذر نشر الستوري.")
        if isinstance(callback.message, Message):
            with suppress(TelegramBadRequest):
                await bot.send_message(
                    chat_id=callback.message.chat.id,
                    business_connection_id=callback.message.business_connection_id,
                    text=error_text,
                )

    @router.callback_query(F.data.startswith("story_music:"))
    async def add_story_music(callback: CallbackQuery, bot: Bot) -> None:
        if adventures is None:
            with suppress(TelegramBadRequest):
                await callback.answer("إضافة الأغنية غير متاحة حاليًا.", show_alert=True)
            return
        token = (callback.data or "").split(":", 1)[-1]
        connection_id = await adventures.begin_music_upload(token, callback.from_user.id)
        if not connection_id:
            with suppress(TelegramBadRequest):
                await callback.answer("انتهت المعاينة أو ما عندك صلاحية.", show_alert=True)
            return
        with suppress(TelegramBadRequest):
            await callback.answer("أرسل ملف صوتي أو بصمة صوتية الآن 🎵", show_alert=True)
        if isinstance(callback.message, Message):
            await bot.send_message(
                chat_id=callback.message.chat.id,
                business_connection_id=connection_id,
                text="أرسل الأغنية كملف صوتي أو بصمة صوتية، وراح أعيد تجهيز الستوري بيها.",
            )

    @router.callback_query(F.data.startswith("story_music_delete:"))
    async def delete_story_music(callback: CallbackQuery, bot: Bot) -> None:
        if adventures is None:
            with suppress(TelegramBadRequest):
                await callback.answer("إدارة الأغنية غير متاحة حاليًا.", show_alert=True)
            return
        token = (callback.data or "").split(":", 1)[-1]
        with suppress(TelegramBadRequest):
            await callback.answer("جاري حذف الأغنية وإعادة تجهيز الستوري 🎬")
        error = await adventures.delete_story_music(token, callback.from_user.id)
        if error and isinstance(callback.message, Message):
            await bot.send_message(
                chat_id=callback.message.chat.id,
                business_connection_id=callback.message.business_connection_id,
                text=error,
            )

    @router.callback_query(F.data.startswith("streak_revive:approve:"))
    async def approve_revive(callback: CallbackQuery, bot: Bot) -> None:
        token = (callback.data or "").rsplit(":", 1)[-1]
        approval = await revive_requests.approve(token, callback.from_user.id)

        if approval.status == "expired":
            await callback.answer(
                "انتهت صلاحية طلب الإحياء. اكتب «احياء الستريك» من جديد.",
                show_alert=True,
            )
            return
        if approval.status == "unauthorized":
            await callback.answer(
                "فقط طرفا هذا الستريك يستطيعان الموافقة.",
                show_alert=True,
            )
            return
        if approval.status == "completed":
            await callback.answer("تم حسم هذا الطلب مسبقًا.", show_alert=True)
            return

        state = approval.state
        if state is None:
            await callback.answer("تعذر قراءة طلب الإحياء.", show_alert=True)
            return

        if not approval.ready:
            record = await repository.get_streak(state.business_connection_id, state.chat_id)
            names = await repository.participant_status(record) if record else {}
            owner_name = await user_label(bot, state.owner_user_id, names.get("owner_name") or "الطرف الأول", repository)
            peer_name = await user_label(bot, state.peer_user_id, names.get("peer_name") or "الطرف الثاني", repository)
            waiting_name = peer_name if state.owner_approved else owner_name
            if callback.inline_message_id:
                with suppress(TelegramBadRequest):
                    await bot.edit_message_text(
                        inline_message_id=callback.inline_message_id,
                        text=_approval_text(state, owner_name, peer_name),
                        reply_markup=_approval_keyboard(token),
                    )
            await callback.answer(
                f"تم تسجيل موافقتك. بانتظار موافقة {waiting_name}."
                if approval.status == "approved"
                else f"موافقتك مسجلة مسبقًا. بانتظار {waiting_name}.",
                show_alert=True,
            )
            return

        result = await repository.revive_streak(
            state.business_connection_id,
            state.chat_id,
        )
        if result.status == "no_balance":
            final_text = "🧊 تعذر إحياء الستريك لأن رصيد الحماية نفد."
        elif result.status != "revived":
            final_text = "تعذر إحياء الستريك لأن حالته لم تعد قابلة للإحياء."
        else:
            final_text = (
                f"🔥 تم إحياء الستريك بموافقة الطرفين. عاد إلى {result.streak}.\n"
                f"الحماية المتبقية: {protection_text(result.freeze_count)}"
            )

        if callback.inline_message_id:
            with suppress(TelegramBadRequest):
                await bot.edit_message_text(
                    inline_message_id=callback.inline_message_id,
                    text=final_text,
                    reply_markup=None,
                )

        await callback.answer(final_text, show_alert=True)

    return router
