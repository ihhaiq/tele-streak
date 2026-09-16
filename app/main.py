from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher

from app.config import load_settings
from app.database.engine import Database
from app.database.repository import Repository
from app.handlers.business import build_router as business_router
from app.handlers.callbacks import build_router as callbacks_router
from app.handlers.connection import build_router as connection_router
from app.handlers.errors import build_router as errors_router
from app.handlers.private import build_router as private_router
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
    bot = Bot(settings.bot_token)
    dp = Dispatcher()

    poses = PoseCatalog(settings.assets_dir)
    renderer = StickerRenderer(poses, settings.rendered_dir)
    streaks = StreakService(repository, settings.timezone, poses)
    stickers = StickerService(
        bot,
        repository,
        renderer,
        settings.ready_stickers_dir,
    )

    dp.include_router(errors_router())
    dp.include_router(connection_router(repository))
    dp.include_router(business_router(streaks, stickers))
    dp.include_router(callbacks_router())
    dp.include_router(private_router(repository))

    scheduler = StreakScheduler(repository, stickers)
    scheduler_task = asyncio.create_task(
        scheduler.run_forever(),
        name="streak-scheduler",
    )

    me = await bot.get_me()
    logging.getLogger(__name__).info("Started @%s (%s)", me.username, me.id)
    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler_task


if __name__ == "__main__":
    asyncio.run(main())
