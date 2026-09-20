import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from aiogram.types import CallbackQuery, Chat, InputRichMessage, Message, User

from app.adventures.rules import Profile
from app.adventures.views import rich_buttons, rich_page, rich_story_page
from app.handlers.adventures import build_router, edit_page, story_menu
from app.handlers.business import build_router as business_router
from app.handlers.streak_mode import build_mode_menu
from app.services.adventure_service import AdventureService
from app.services.rich_status import build_streak_rich_message
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
    assert menu.inline_keyboard[0][0].text == "صورة"



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


def test_rich_navigation_uses_compact_borderless_table():
    html = rich_buttons(10, 20, include_mode=True)
    assert html.startswith("<table compact>")
    assert "bordered" not in html
    assert "striped" not in html
    assert html.count("<tg-button") == 5
    assert html.count("<tr>") == 3
    assert "streak_mode:open:10:20" in html
    assert "adv:compare:10:20" in html


def test_status_details_use_rich_list_without_duplicate_inline_markup():
    rich = build_streak_rich_message(
        current=12,
        longest=20,
        completed_days=30,
        break_count=0,
        freeze_count=3,
        last_completed_day="2026-09-20",
        owner_user_id=10,
        chat_id=20,
        adventure_profile=Profile(),
    )
    assert "<h3>الخيارات</h3><table compact>" in rich.html
    assert "<b>12 يوم</b> حاليًا" in rich.html
    assert "إجمالي أيام الستريك" not in rich.html
    assert rich.html.count("<li>") >= 3
    assert rich.html.count("<table compact>") >= 1


def test_compare_page_uses_two_column_compact_table():
    profile = Profile(tracked_since="2026-09-01", automatic_saves=2)
    profile.stats["owner"].update(
        name="حسين",
        started=4,
        late=1,
        days=7,
        saves=2,
        contribution=60,
    )
    profile.stats["peer"].update(
        name="صديق",
        started=3,
        late=2,
        days=7,
        saves=2,
        contribution=40,
    )
    rich = rich_page(profile, {}, "compare", 10, 20)
    assert rich.html.startswith("<h1>مقارنة ودية</h1><hr/>")
    assert "<table compact>" in rich.html
    assert "<th>الطرف الأول</th><th>الطرف الثاني</th>" in rich.html
    assert "<b>حسين</b>" in rich.html
    assert "<b>صديق</b>" in rich.html
    assert "bordered" not in rich.html
    assert "<details><summary>الحساب</summary>" in rich.html
    assert "<details><summary>الخيارات</summary>" in rich.html


def test_story_page_keeps_choices_as_rich_buttons():
    rich = rich_story_page(10, 20)
    assert "adv:image:10:20" in rich.html
    assert "adv:video5:10:20" in rich.html
    assert "adv:video10:10:20" in rich.html
    assert rich.html.count("<table compact>") >= 2
    assert "bordered" not in rich.html
    assert "النشر يتم بعد تأكيدك" in rich.html


def test_successful_rich_edit_removes_existing_inline_keyboard():
    async def run():
        bot = SimpleNamespace(edit_message_text=AsyncMock())
        await edit_page(
            callback(),
            bot,
            InputRichMessage(html="<p>test</p>"),
            "fallback",
            "fallback-keyboard",
        )
        call = bot.edit_message_text.await_args
        assert call.kwargs["rich_message"].html == "<p>test</p>"
        assert call.kwargs["reply_markup"] is None

    asyncio.run(run())


def test_mode_menu_uses_one_button_per_line():
    rich = build_mode_menu(10, 20, "message")
    assert "<h1>وضع الستريك</h1>" in rich.html
    assert "<tg-button-row" not in rich.html
    assert rich.html.count("<li>") == 4
    assert "الحالي: <b>رسالة</b>" in rich.html


def test_fallback_navigation_is_one_button_per_row():
    from app.adventures.views import navigation

    keyboard = navigation(10, 20)
    assert len(keyboard.inline_keyboard) == 5
    assert all(len(row) == 1 for row in keyboard.inline_keyboard)


def test_tasks_page_explains_combo_in_plain_iraqi():
    from app.adventures.rules import make_day
    import random

    profile = Profile()
    daily = make_day("2026-09-20", profile, 12, random.Random(8))
    rich = rich_page(profile, daily, "tasks", 10, 20)

    assert "<table compact>" in rich.html
    assert "<th>المهمة</th><th>XP</th>" in rich.html
    assert "تتجدد كل 6 ساعات" in rich.html
    assert "الـCombo يعني شكد يوم ورا بعض" in rich.html
    assert "إذا خلصتوه بعد 10" in rich.html
    assert "يرجع ×0" in rich.html
