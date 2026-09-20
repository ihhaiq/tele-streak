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
from app.handlers.adventures import build_router as adventures_router
from app.handlers.business import build_router as business_router
from app.handlers.callbacks import build_router as callbacks_router
from app.handlers.connection import build_router as connection_router
from app.handlers.errors import build_router as errors_router
from app.handlers.guest import build_router as guest_router
from app.handlers.guest_callbacks import build_router as guest_callbacks_router
from app.handlers.private import build_router as private_router
from app.handlers.streak_mode import build_router as streak_mode_router
from app.handlers.streak_test import build_router as streak_test_router
from app.services.adventure_service import AdventureService
from app.services.guest_delivery import GuestDeliveryService
from app.services.scheduler import StreakScheduler
from app.services.sticker_service import StickerService
from app.services.streak_service import StreakService
from app.services.streak_test_service import StreakTestService
from app.stickers.poses import PoseCatalog
from app.stickers.renderer import StickerRenderer
from app.story.web import StoryShareWeb


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
    me = await bot.get_me()

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
    adventures = AdventureService(bot, repository, guests, music_path=settings.story_music_path)
    story_web = None
    if settings.public_base_url and me.username:
        story_web = StoryShareWeb(
            bot_token=settings.bot_token,
            bot_username=me.username,
            public_base_url=settings.public_base_url,
            adventures=adventures,
            share_dir=settings.rendered_dir / "story_share",
            ttl_seconds=settings.story_share_ttl_seconds,
            main_app_enabled=bool(getattr(me, "has_main_web_app", False)),
        )
        await story_web.start("0.0.0.0", settings.http_port)
        if not story_web.enabled:
            logging.getLogger(__name__).warning(
                "Story Mini App endpoint is ready, but Telegram Main Mini App is not enabled in BotFather."
            )
    streak_tests = StreakTestService(repository)
    dp.include_router(errors_router())
    dp.include_router(connection_router(repository, streaks))
    dp.include_router(streak_test_router(repository, stickers, guests, streak_tests))
    dp.include_router(
        business_router(streaks, stickers, repository, activations, guests, adventures)
    )
    dp.include_router(guest_router(repository, stickers, revive_requests, guests, adventures))
    dp.include_router(adventures_router(repository, adventures, story_web))
    dp.include_router(streak_mode_router(repository, adventures))
    dp.include_router(guest_callbacks_router(repository, revive_requests))
    dp.include_router(callbacks_router(repository, activations, streaks))
    dp.include_router(private_router(repository, stickers))

    scheduler = StreakScheduler(repository, stickers, guests)
    scheduler_task = asyncio.create_task(
        scheduler.run_forever(),
        name="streak-scheduler",
    )

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
        if story_web is not None:
            await story_web.close()
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
