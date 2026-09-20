from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

_BUSINESS_CONNECTION_INVALID = "BUSINESS_CONNECTION_INVALID"
_BUSINESS_PEER_INVALID = "BUSINESS_PEER_INVALID"
_BUSINESS_TRANSPORT_CODES = {
    _BUSINESS_CONNECTION_INVALID,
    _BUSINESS_PEER_INVALID,
}


def telegram_business_error_code(error: BaseException) -> str | None:
    message = str(error).upper()
    return next(
        (code for code in _BUSINESS_TRANSPORT_CODES if code in message),
        None,
    )


def is_business_transport_error(error: BaseException) -> bool:
    return (
        isinstance(error, (TelegramBadRequest, TelegramForbiddenError))
        and telegram_business_error_code(error) is not None
    )


def is_business_connection_invalid(error: BaseException) -> bool:
    return (
        isinstance(error, (TelegramBadRequest, TelegramForbiddenError))
        and telegram_business_error_code(error) == _BUSINESS_CONNECTION_INVALID
    )
