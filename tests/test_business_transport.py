import asyncio
from types import SimpleNamespace

from aiogram.exceptions import TelegramBadRequest

from app.services.business_errors import (
    is_business_connection_invalid,
    is_business_transport_error,
    telegram_business_error_code,
)
from app.services.guest_delivery import GuestDeliveryService


class FakeRepository:
    def __init__(self, resolved="bc-new"):
        self.resolved = resolved
        self.created = []
        self.finished = []
        self.disabled = []

    async def resolve_active_connection_id(self, connection_id):
        return self.resolved

    async def create_guest_streak_request(
        self,
        connection_id,
        chat_id,
        *,
        ttl_seconds,
        cooldown_seconds,
    ):
        self.created.append((connection_id, chat_id))
        return "GuestToken12"

    async def finish_guest_streak_request(self, token):
        self.finished.append(token)

    async def set_guest_streak_summon_message(self, token, message_id):
        pass

    async def disable_connection(self, connection_id):
        self.disabled.append(connection_id)


class FakeBot:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(message_id=77)


def bad_request(message):
    return TelegramBadRequest(method=object(), message=message)


def test_business_error_classifier():
    peer = bad_request("Bad Request: BUSINESS_PEER_INVALID")
    connection = bad_request("Bad Request: BUSINESS_CONNECTION_INVALID")
    other = bad_request("Bad Request: message not found")

    assert is_business_transport_error(peer)
    assert is_business_transport_error(connection)
    assert not is_business_transport_error(other)
    assert telegram_business_error_code(peer) == "BUSINESS_PEER_INVALID"
    assert telegram_business_error_code(connection) == "BUSINESS_CONNECTION_INVALID"
    assert is_business_connection_invalid(connection)
    assert not is_business_connection_invalid(peer)


def test_guest_delivery_rebinds_old_connection_before_send():
    async def scenario():
        repository = FakeRepository("bc-new")
        bot = FakeBot()
        service = GuestDeliveryService(bot, repository)
        service._username = "HStreakBot"
        service._supported = True

        result = await service.summon(
            event="status",
            connection_id="bc-old",
            chat_id=20,
        )

        assert result.sent
        assert repository.created == [("bc-new", 20)]
        assert bot.calls[0]["business_connection_id"] == "bc-new"

    asyncio.run(scenario())


def test_invalid_business_connection_is_disabled_without_retry_chain():
    async def scenario():
        repository = FakeRepository("bc-new")
        bot = FakeBot(
            bad_request("Bad Request: BUSINESS_CONNECTION_INVALID")
        )
        service = GuestDeliveryService(bot, repository)
        service._username = "HStreakBot"
        service._supported = True

        result = await service.summon(
            event="status",
            connection_id="bc-old",
            chat_id=20,
        )

        assert not result
        assert result.transport_unavailable
        assert result.error_code == "BUSINESS_CONNECTION_INVALID"
        assert repository.finished == ["GuestToken12"]
        assert repository.disabled == ["bc-new"]
        assert len(bot.calls) == 1

    asyncio.run(scenario())


def test_invalid_business_peer_is_terminal_but_does_not_disable_account():
    async def scenario():
        repository = FakeRepository("bc-new")
        bot = FakeBot(
            bad_request("Bad Request: BUSINESS_PEER_INVALID")
        )
        service = GuestDeliveryService(bot, repository)
        service._username = "HStreakBot"
        service._supported = True

        result = await service.summon(
            event="success",
            connection_id="bc-old",
            chat_id=20,
        )

        assert not result
        assert result.transport_unavailable
        assert result.error_code == "BUSINESS_PEER_INVALID"
        assert repository.disabled == []
        assert len(bot.calls) == 1

    asyncio.run(scenario())
