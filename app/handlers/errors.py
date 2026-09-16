from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)


def build_router() -> Router:
    router = Router(name="errors")

    @router.errors()
    async def on_error(event: ErrorEvent) -> bool:
        update_id = getattr(event.update, "update_id", None)
        logger.exception(
            "UNHANDLED_UPDATE_ERROR update_id=%s error=%r",
            update_id,
            event.exception,
        )
        return True

    return router
