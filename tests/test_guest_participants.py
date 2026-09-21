from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import (
    InlineQueryResultCachedSticker,
    InputRichMessageContent,
    InputTextMessageContent,
)

from app.adventures.rules import Profile
from app.database.repository import GuestStreakRequest
from app.handlers.guest import build_router
from app.handlers.guest_callbacks import build_router as callback_router


def context(event, *, reject_rich=False):
    streak = SimpleNamespace(business_connection_id="bc", chat_id=20,
                             current_streak=1, longest_streak=1, completed_days=1,
                             break_count=0, freeze_count=3, last_completed_day="2026-09-21",
                             streak_mode="message", owner_sent_day="2026-09-21", peer_sent_day=None)
    repo = SimpleNamespace(
        get_guest_streak_request=AsyncMock(return_value=GuestStreakRequest("AbCd_123", "bc", 20, None)),
        get_streak=AsyncMock(return_value=streak),
        get_connection_timezone=AsyncMock(return_value="Asia/Baghdad"),
        get_owner_id=AsyncMock(return_value=10),
        participant_status=AsyncMock(return_value=dict(owner_name="حسين", peer_name="أحمد",
                                                       owner_sent_day="2026-09-21", peer_sent_day=None)),
        get_account_name=AsyncMock(side_effect=lambda uid: {10: "حسين", 20: "أحمد"}[uid]),
        finish_guest_streak_request=AsyncMock(),
    )
    reply = AsyncMock()
    if reject_rich:
        reply.side_effect = [TelegramBadRequest(method=SendMessage(chat_id=20, text="test"),
                                                message="rich rejected"), None]
    message = SimpleNamespace(text=f"streak:{event}:AbCd_123", guest_query_id="q",
                              chat=SimpleNamespace(id=20), answer_guest_query=reply,
                              bot=SimpleNamespace(get_chat=AsyncMock()))
    adventures = SimpleNamespace(snapshot=AsyncMock(return_value=(Profile(), {"latest_notice": "مهمة خلصت"})),
                                 celebration_file_id=AsyncMock(return_value="sticker"))
    guests = SimpleNamespace(summon=AsyncMock(return_value=True))
    revive = SimpleNamespace(create_or_get=AsyncMock(return_value=SimpleNamespace(
        owner_user_id=10, peer_user_id=20, owner_approved=False, peer_approved=True, token="AbCd_123")))
    return repo, message, adventures, guests, revive


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["adventure", "celebration"])
async def test_adventure_has_no_revive_state_lookup(event):
    repo, message, adventures, guests, revive = context(event)
    handler = build_router(repo, SimpleNamespace(), revive, guests, adventures).guest_message.handlers[0].callback
    await handler(message)
    message.answer_guest_query.assert_awaited_once()
    revive.create_or_get.assert_not_awaited()
    message.bot.get_chat.assert_not_awaited()
    repo.finish_guest_streak_request.assert_awaited_once_with("AbCd_123")


@pytest.mark.asyncio
async def test_revive_displays_persisted_names():
    repo, message, adventures, guests, revive = context("revive")
    await build_router(repo, SimpleNamespace(), revive, guests, adventures).guest_message.handlers[0].callback(message)
    text = message.answer_guest_query.await_args.args[0].input_message_content.message_text
    assert "حسين: ⏳" in text and "أحمد: ✅" in text
    assert "الطرف الأول" not in text and "الطرف الثاني" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("event", ["status", "broken_notice"])
async def test_rich_rejection_sends_exactly_one_fallback(event, monkeypatch):
    monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-21")
    repo, message, adventures, guests, revive = context(event, reject_rich=True)
    await build_router(repo, SimpleNamespace(), revive, guests, adventures).guest_message.handlers[0].callback(message)
    calls = message.answer_guest_query.await_args_list
    assert len(calls) == 2
    assert isinstance(calls[0].args[0].input_message_content, InputRichMessageContent)
    assert isinstance(calls[1].args[0].input_message_content, InputTextMessageContent)
    if event == "status":
        text = calls[1].args[0].input_message_content.message_text
        assert "✅ أكمل اليوم: حسين" in text and "⏳ بانتظار: أحمد" in text
        assert calls[1].args[0].reply_markup is not None
    else:
        guests.summon.assert_awaited_once()
    repo.finish_guest_streak_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_success_rejection_refreshes_sticker_and_cleans_summon():
    repo, message, adventures, guests, revive = context("success")
    repo.get_guest_streak_request.return_value = GuestStreakRequest(
        "AbCd_123", "bc", 20, 77
    )
    repo.get_sticker_file_id = AsyncMock(return_value="stale-file-id")
    repo.set_sticker_file_id = AsyncMock()
    repo.delete_sticker_file_id = AsyncMock()
    message.bot.delete_business_messages = AsyncMock()
    message.answer_guest_query.side_effect = [
        TelegramBadRequest(
            method=SendMessage(chat_id=20, text="test"),
            message="wrong file identifier",
        ),
        None,
    ]
    pack = SimpleNamespace(
        cached_file_id=Mock(return_value=None),
        invalidate_cached_file_id=Mock(),
        refresh_numbered_file_id=AsyncMock(return_value="fresh-file-id"),
    )
    stickers = SimpleNamespace(pack=pack)

    handler = build_router(
        repo, stickers, revive, guests, adventures
    ).guest_message.handlers[0].callback
    await handler(message)

    calls = message.answer_guest_query.await_args_list
    assert len(calls) == 2
    assert isinstance(calls[0].args[0], InlineQueryResultCachedSticker)
    assert calls[0].args[0].sticker_file_id == "stale-file-id"
    assert isinstance(calls[1].args[0], InlineQueryResultCachedSticker)
    assert calls[1].args[0].sticker_file_id == "fresh-file-id"
    repo.delete_sticker_file_id.assert_awaited_once_with("streak:1")
    pack.invalidate_cached_file_id.assert_called_once_with("1")
    repo.set_sticker_file_id.assert_awaited_once_with(
        "streak:1", "fresh-file-id"
    )
    repo.finish_guest_streak_request.assert_awaited_once_with("AbCd_123")
    message.bot.delete_business_messages.assert_awaited_once_with(
        business_connection_id="bc",
        message_ids=[77],
    )


@pytest.mark.asyncio
async def test_success_rejection_falls_back_to_text_when_refresh_fails():
    repo, message, adventures, guests, revive = context("success")
    repo.get_sticker_file_id = AsyncMock(return_value="stale-file-id")
    repo.set_sticker_file_id = AsyncMock()
    repo.delete_sticker_file_id = AsyncMock()
    message.answer_guest_query.side_effect = [
        TelegramBadRequest(
            method=SendMessage(chat_id=20, text="test"),
            message="wrong file identifier",
        ),
        None,
    ]
    pack = SimpleNamespace(
        cached_file_id=Mock(return_value=None),
        invalidate_cached_file_id=Mock(),
        refresh_numbered_file_id=AsyncMock(return_value=None),
    )
    stickers = SimpleNamespace(pack=pack)

    handler = build_router(
        repo, stickers, revive, guests, adventures
    ).guest_message.handlers[0].callback
    await handler(message)

    calls = message.answer_guest_query.await_args_list
    assert len(calls) == 2
    assert isinstance(calls[0].args[0], InlineQueryResultCachedSticker)
    fallback = calls[1].args[0]
    assert isinstance(fallback.input_message_content, InputTextMessageContent)
    assert fallback.input_message_content.message_text == "🔥 الستريك: 1"
    assert fallback.reply_markup is not None
    repo.delete_sticker_file_id.assert_awaited_once_with("streak:1")
    repo.finish_guest_streak_request.assert_awaited_once_with("AbCd_123")


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_approved,expected", [(True, "أحمد"), (False, "حسين")])
async def test_revive_callback_waits_for_the_actual_other_person(owner_approved, expected):
    repo, _, _, _, _ = context("revive")
    state = SimpleNamespace(business_connection_id="bc", chat_id=20, owner_user_id=10, peer_user_id=20, owner_approved=owner_approved,
                            peer_approved=not owner_approved)
    revive = SimpleNamespace(approve=AsyncMock(return_value=SimpleNamespace(
        status="approved", ready=False, state=state)))
    callback = SimpleNamespace(data="streak_revive:approve:AbCd_123", inline_message_id="inline",
                               from_user=SimpleNamespace(id=10 if owner_approved else 20), answer=AsyncMock())
    bot = SimpleNamespace(edit_message_text=AsyncMock())
    handler = callback_router(repo, revive).callback_query.handlers[-1].callback
    await handler(callback, bot)
    assert f"بانتظار موافقة {expected}" in callback.answer.await_args.args[0]


def test_production_entrypoint_imports_all_routers():
    import app.main

    assert callable(app.main.main)
