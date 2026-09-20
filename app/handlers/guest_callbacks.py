from __future__ import annotations

from contextlib import suppress

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.database.revive_request_repository import ReviveApprovalState, ReviveRequestRepository
from app.database.repository import Repository
from app.services.rich_status import protection_text


def _approval_text(state: ReviveApprovalState) -> str:
    owner = "✅" if state.owner_approved else "⏳"
    peer = "✅" if state.peer_approved else "⏳"
    return (
        "🧊 طلب إحياء الستريك\n\n"
        f"الطرف الأول: {owner}\n"
        f"الطرف الثاني: {peer}\n\n"
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
            await callback.answer(final_text, show_alert=True)
            return

        messages = {
            "expired": "انتهت صلاحية المعاينة. سوي معاينة جديدة.",
            "unauthorized": "فقط طرفا الستريك يگدرون ينشرون هاي الستوري.",
            "publishing": "الستوري قيد النشر حاليًا.",
            "permission": (
                "فعّل صلاحية إدارة الستوريات للبوت من إعدادات Telegram Business."
            ),
            "failed": "Telegram رفض نشر الستوري أو صار خطأ. جرب مرة ثانية.",
        }
        await callback.answer(
            messages.get(result.status, "تعذر نشر الستوري."),
            show_alert=True,
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
            if callback.inline_message_id:
                with suppress(TelegramBadRequest):
                    await bot.edit_message_text(
                        inline_message_id=callback.inline_message_id,
                        text=_approval_text(state),
                        reply_markup=_approval_keyboard(token),
                    )
            await callback.answer(
                "تم تسجيل موافقتك. بانتظار موافقة الطرف الثاني."
                if approval.status == "approved"
                else "موافقتك مسجلة مسبقًا. بانتظار الطرف الثاني.",
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
