import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import CallbackQuery, Chat, InputRichMessage, Message, User

from app.handlers.adventures import build_router, edit_page, story_menu
from app.handlers.business import build_router as business_router
from app.services.adventure_service import AdventureService
from app.services.streak_service import Completion


def callback(user_id=10, data="adv:tasks:10:20"):
    return CallbackQuery(
        id="q",
        from_user=User(id=user_id, is_bot=False, first_name="A"),
        chat_instance="chat",
        inline_message_id="inline",
        data=data,
    )


def test_story_menu_offers_still_image_first():
    menu = story_menu(10, 20)
    assert menu.inline_keyboard[0][0].callback_data == "adv:image:10:20"
    assert "صورة ستوري" in menu.inline_keyboard[0][0].text



def test_outsider_cannot_read_progress_or_generate_story():
    async def run():
        record = SimpleNamespace(peer_user_id=30, chat_id=20)
        repo = SimpleNamespace(get_owner_streak=AsyncMock(return_value=record))
        adventures = SimpleNamespace(snapshot=AsyncMock(), prepare_story_preview=AsyncMock())
        router = build_router(repo, adventures)
        bot = Bot("123456:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi")
        bot.session = AsyncMock()
        try:
            for data in ("adv:compare:10:20", "adv:image:10:20", "adv:video5:10:20"):
                await router.callback_query.handlers[0].callback(
                    callback(999, data).as_(bot), bot
                )
            adventures.snapshot.assert_not_awaited()
            adventures.prepare_story_preview.assert_not_awaited()
        finally:
            await bot.session.close()

    asyncio.run(run())


def test_inline_rich_rejection_falls_back_without_losing_buttons():
    async def run():
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(
                side_effect=[
                    TelegramBadRequest(
                        method=EditMessageText(text="test"), message="rich rejected"
                    ),
                    None,
                ]
            )
        )
        await edit_page(
            callback(),
            bot,
            InputRichMessage(html="<p>test</p>"),
            "fallback",
            "keyboard",
        )
        calls = bot.edit_message_text.await_args_list
        assert calls[0].kwargs["inline_message_id"] == "inline"
        assert calls[1].kwargs["text"] == "fallback"
        assert calls[1].kwargs["reply_markup"] == "keyboard"

    asyncio.run(run())


def test_notification_mute_and_guest_delivery():
    async def run():
        repo = SimpleNamespace(
            database=None,
            get_streak=AsyncMock(
                return_value=SimpleNamespace(notifications_enabled=False)
            ),
            get_owner_id=AsyncMock(return_value=10),
        )
        guests = SimpleNamespace(summon=AsyncMock(return_value=True))
        bot = SimpleNamespace(send_sticker=AsyncMock(), send_message=AsyncMock())
        service = AdventureService(bot, repo, guests)
        completion = Completion(True, 1, "pose", False, True, True)
        await service.after_activity("bc", 20, completion)
        guests.summon.assert_not_awaited()
        repo.get_streak.return_value.notifications_enabled = True
        await service.after_activity("bc", 20, completion)
        assert [c.kwargs["event"] for c in guests.summon.await_args_list] == [
            "celebration",
            "adventure",
        ]
        bot.send_sticker.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    asyncio.run(run())


def test_nonmatching_media_reaches_tasks_and_keeps_success_flow():
    async def run():
        streaks = SimpleNamespace(
            get_owner_id=AsyncMock(return_value=10),
            register_message=AsyncMock(return_value=Completion(False)),
        )
        repo = SimpleNamespace(
            get_streak=AsyncMock(
                return_value=SimpleNamespace(is_enabled=True, streak_mode="message")
            )
        )
        activations = SimpleNamespace(is_active=AsyncMock(return_value=True))
        adventures = SimpleNamespace(after_activity=AsyncMock())
        guests = SimpleNamespace(summon=AsyncMock())
        router = business_router(
            streaks, SimpleNamespace(), repo, activations, guests, adventures
        )
        message = Message(
            message_id=1,
            date=1,
            business_connection_id="bc",
            chat=Chat(id=20, type="private"),
            from_user=User(id=30, is_bot=False, first_name="B"),
            photo=[dict(file_id="f", file_unique_id="u", width=10, height=10)],
        )
        await router.business_message.handlers[0].callback(message)
        streaks.register_message.assert_awaited_once()
        adventures.after_activity.assert_awaited_once()
        guests.summon.assert_not_awaited()

    asyncio.run(run())


def test_sticker_page_requests_new_message_when_text_edit_is_impossible():
    async def run():
        bot = SimpleNamespace(
            edit_message_text=AsyncMock(
                side_effect=TelegramBadRequest(
                    method=EditMessageText(text="test"), message="no text in message"
                )
            )
        )
        result = await edit_page(
            callback(), bot, InputRichMessage(html="<p>x</p>"), "x", None
        )
        assert result is False

    asyncio.run(run())
