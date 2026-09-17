from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession

from app.config import load_settings
from app.database.activation_repository import StreakActivationRepository
from app.database.engine import Database
from app.database.repository import Repository
from app.database.revive_request_repository import ReviveRequestRepository
from app.handlers.business import build_router as business_router
from app.handlers.callbacks import build_router as callbacks_router
from app.handlers.connection import build_router as connection_router
from app.handlers.errors import build_router as errors_router
from app.handlers.guest import build_router as guest_router
from app.handlers.guest_callbacks import build_router as guest_callbacks_router
from app.handlers.private import build_router as private_router
from app.services.guest_delivery import GuestDeliveryService
from app.services.scheduler import StreakScheduler
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService
from app.stickers.poses import PoseCatalog
from app.stickers.renderer import StickerRenderer


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    settings = load_settings()
    database = Database(settings.database_path)
    await database.init()

    repository = Repository(database)
    activations = StreakActivationRepository(database)
    revive_requests = ReviveRequestRepository(database)
    session = AiohttpSession(timeout=60)
    bot = Bot(
        settings.bot_token,
        session=session,
        default=DefaultBotProperties(link_preview_is_disabled=True),
    )
    dp = Dispatcher()

    poses = PoseCatalog(settings.assets_dir)
    renderer = StickerRenderer(poses, settings.rendered_dir)
    streaks = StreakService(repository, activations, settings.timezone, poses)
    stickers = StickerService(
        bot,
        repository,
        renderer,
        settings.ready_stickers_dir,
        message_effect_id=settings.message_effect_id,
        sticker_set_owner_id=settings.sticker_set_owner_id,
        sticker_set_title=settings.sticker_set_title,
    )
    guests = GuestDeliveryService(bot, repository)

    dp.include_router(errors_router())
    dp.include_router(connection_router(repository, streaks))
    dp.include_router(
        business_router(streaks, stickers, repository, activations, guests)
    )
    dp.include_router(guest_router(repository, stickers, revive_requests))
    dp.include_router(guest_callbacks_router(repository, revive_requests))
    dp.include_router(callbacks_router(repository, activations, streaks))
    dp.include_router(private_router(repository, stickers))

    scheduler = StreakScheduler(repository, stickers, guests)
    scheduler_task = asyncio.create_task(
        scheduler.run_forever(),
        name="streak-scheduler",
    )

    me = await bot.get_me()
    logging.getLogger(__name__).info(
        "Started @%s (%s) guest_mode=%s",
        me.username,
        me.id,
        bool(me.supports_guest_queries),
    )
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task
        await bot.session.close()
        await database.close()


def run() -> None:
    """Prefer uvloop where it is available; it roughly halves event-loop overhead."""
    try:
        import uvloop
    except ImportError:
        asyncio.run(main())
    else:
        uvloop.run(main())


if __name__ == "__main__":
    with suppress(KeyboardInterrupt):
        run()
