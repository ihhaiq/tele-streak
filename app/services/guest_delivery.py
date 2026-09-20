from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyParameters

from app.database.repository import Repository
from app.services.business_errors import (
    is_business_connection_invalid,
    is_business_transport_error,
    telegram_business_error_code,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GuestDeliveryResult:
    sent: bool
    transport_unavailable: bool = False
    error_code: str | None = None

    def __bool__(self) -> bool:
        return self.sent

    def __str__(self) -> str:
        return str(self.sent)


class GuestDeliveryService:
    """Invoke the bot in guest mode from a Telegram Business chat."""

    def __init__(self, bot: Bot, repository: Repository):
        self.bot = bot
        self.repository = repository
        self._username: str | None = None
        self._supported: bool | None = None

    async def _identity(self) -> tuple[str | None, bool]:
        if self._supported is not None:
            return self._username, self._supported
        try:
            me = await self.bot.get_me()
        except Exception:
            logger.exception("STREAK_GUEST_GET_ME_FAILED")
            self._supported = False
            return None, False
        self._username = me.username
        self._supported = bool(me.username and me.supports_guest_queries)
        return self._username, self._supported

    async def summon(
        self,
        *,
        event: str,
        connection_id: str,
        chat_id: int,
        reply_to_message_id: int | None = None,
        ttl_seconds: int = 60,
    ) -> GuestDeliveryResult:
        resolved_connection = await self.repository.resolve_active_connection_id(
            connection_id
        )
        if resolved_connection and resolved_connection != connection_id:
            logger.info(
                "STREAK_GUEST_CONNECTION_REBOUND old=%s new=%s chat=%s",
                connection_id,
                resolved_connection,
                chat_id,
            )
            connection_id = resolved_connection

        username, supported = await self._identity()
        if not supported or not username:
            logger.warning(
                "STREAK_GUEST_UNAVAILABLE event=%s connection=%s chat=%s",
                event,
                connection_id,
                chat_id,
            )
            return GuestDeliveryResult(False)

        token = await self.repository.create_guest_streak_request(
            connection_id,
            chat_id,
            ttl_seconds=ttl_seconds,
            cooldown_seconds=0,
        )
        if token is None:
            logger.warning(
                "STREAK_GUEST_TOKEN_UNAVAILABLE event=%s connection=%s chat=%s",
                event,
                connection_id,
                chat_id,
            )
            return GuestDeliveryResult(False)

        try:
            summon = await self.bot.send_message(
                chat_id=chat_id,
                business_connection_id=connection_id,
                text=f"@{username} streak:{event}:{token}",
                disable_notification=True,
                reply_parameters=(
                    ReplyParameters(message_id=reply_to_message_id)
                    if reply_to_message_id is not None
                    else None
                ),
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            await self.repository.finish_guest_streak_request(token)
            transport_unavailable = is_business_transport_error(error)
            error_code = telegram_business_error_code(error)
            if is_business_connection_invalid(error):
                await self.repository.disable_connection(connection_id)
            logger.warning(
                "STREAK_GUEST_INVOKE_REJECTED event=%s connection=%s chat=%s "
                "transport_unavailable=%s code=%s error=%s",
                event,
                connection_id,
                chat_id,
                transport_unavailable,
                error_code,
                error,
            )
            return GuestDeliveryResult(
                False,
                transport_unavailable=transport_unavailable,
                error_code=error_code,
            )

        await self.repository.set_guest_streak_summon_message(
            token,
            summon.message_id,
        )
        logger.info(
            "STREAK_GUEST_INVOKED event=%s connection=%s chat=%s message=%s",
            event,
            connection_id,
            chat_id,
            summon.message_id,
        )
        return GuestDeliveryResult(True)
