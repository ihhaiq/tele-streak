from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from app.adventures.views import navigation, progress_text
from app.database.adventure_repository import AdventureRepository
from app.story.renderer import StoryRenderer, write_celebration

logger = logging.getLogger(__name__)


class AdventureService:
    def __init__(self, bot, repository, guests, *, music_path: Path | None = None):
        self.bot = bot
        self.repository = repository
        self.data = AdventureRepository(repository.database)
        self.guests = guests
        self.renderer = StoryRenderer(music_path)
        self._story_slots = asyncio.Semaphore(2)
        self._celebration_lock = asyncio.Lock()

    async def snapshot(self, connection_id, chat_id):
        zone = await self.repository.get_connection_timezone(connection_id)
        return await self.data.snapshot(
            connection_id, chat_id, datetime.now(ZoneInfo(zone or "Asia/Baghdad"))
        )

    async def celebration_file_id(self, owner_id: int) -> str:
        async with self._celebration_lock:
            key = "special:celebration:v1"
            cached = await self.repository.get_sticker_file_id(key)
            if cached:
                return cached
            with TemporaryDirectory(prefix="streak-celebration-") as directory:
                path = await asyncio.to_thread(
                    write_celebration, Path(directory) / "celebration.webp"
                )
                uploaded = await self.bot.upload_sticker_file(
                    user_id=owner_id, sticker=FSInputFile(path), sticker_format="static"
                )
                await self.repository.set_sticker_file_id(key, uploaded.file_id)
                return uploaded.file_id

    async def after_activity(self, connection_id, chat_id, completion):
        if not (completion.adventure_notice or completion.celebrate):
            return
        record = await self.repository.get_streak(connection_id, chat_id)
        if record is None or not record.notifications_enabled:
            return
        owner = await self.repository.get_owner_id(connection_id)
        if owner is None:
            return
        if completion.celebrate:
            try:
                sent = await self.guests.summon(
                    event="celebration", connection_id=connection_id, chat_id=chat_id
                )
                if not sent:
                    sticker = await self.celebration_file_id(owner)
                    await self.bot.send_sticker(
                        chat_id=chat_id,
                        business_connection_id=connection_id,
                        sticker=sticker,
                        reply_markup=navigation(owner, chat_id),
                    )
            except Exception:
                logger.exception("STREAK_CELEBRATION_DELIVERY_FAILED")
        if completion.adventure_notice:
            try:
                sent = await self.guests.summon(
                    event="adventure", connection_id=connection_id, chat_id=chat_id
                )
                if not sent:
                    profile, state = await self.snapshot(connection_id, chat_id)
                    await self.bot.send_message(
                        chat_id=chat_id,
                        business_connection_id=connection_id,
                        text=state["latest_notice"] + "\n\n" + progress_text(profile),
                        reply_markup=navigation(owner, chat_id),
                        disable_notification=True,
                    )
            except Exception:
                logger.exception("STREAK_ADVENTURE_DELIVERY_FAILED")

    async def _participant(self, user_id: int, fallback: str, path: Path):
        name, file_id = fallback, None
        try:
            chat = await self.bot.get_chat(user_id)
            name = " ".join(filter(None, (chat.first_name, chat.last_name))) or fallback
            if chat.photo:
                file_id = chat.photo.big_file_id
        except (TelegramAPIError, OSError, TimeoutError):
            logger.debug("STORY_NAME_UNAVAILABLE user=%s", user_id)
        try:
            if file_id is None:
                photos = await self.bot.get_user_profile_photos(user_id, limit=1)
                if photos.photos:
                    file_id = photos.photos[0][-1].file_id
            if file_id:
                await self.bot.download(file_id, destination=path)
                return name, path
        except (TelegramAPIError, OSError, TimeoutError):
            # الصورة المخفية أو غير المتاحة ما تمنع الستوري.
            logger.info("STORY_AVATAR_UNAVAILABLE user=%s", user_id)
        return name, None

    async def send_story(self, record, owner: int, duration: int) -> str | None:
        if record.current_streak < 1:
            return "كملوا أول يوم حتى نسوي ستوري 🔥"
        if self._story_slots.locked():
            return "Jake دا يجهز ستوريات، جرب بعد شوي 😆"
        async with self._story_slots:
            profile, _ = await self.snapshot(
                record.business_connection_id, record.chat_id
            )
            if not await self.data.claim_story(
                record.business_connection_id,
                record.chat_id,
                datetime.now(timezone.utc).timestamp(),
            ):
                return "انتظر دقيقة بين كل ستوري والثاني 🎬"
            with TemporaryDirectory(prefix="streak-story-") as directory:
                folder = Path(directory)
                first, second = await asyncio.gather(
                    self._participant(
                        owner,
                        profile.stats["owner"]["name"] or "الطرف الأول",
                        folder / "owner.jpg",
                    ),
                    self._participant(
                        record.peer_user_id or record.chat_id,
                        profile.stats["peer"]["name"] or "الطرف الثاني",
                        folder / "peer.jpg",
                    ),
                )
                job = asyncio.create_task(
                    asyncio.to_thread(
                        self.renderer.render,
                        folder,
                        days=record.current_streak,
                        names=(first[0], second[0]),
                        photos=(first[1], second[1]),
                        duration=duration,
                    )
                )
                try:
                    path = await asyncio.shield(job)
                except asyncio.CancelledError:
                    # لا نمسح الملفات قبل انتهاء عامل الفيديو.
                    try:
                        await job
                    finally:
                        raise
                await self.bot.send_video(
                    chat_id=record.chat_id,
                    business_connection_id=record.business_connection_id,
                    video=FSInputFile(path, filename="streak-story.mp4"),
                    duration=duration,
                    width=720,
                    height=1280,
                    supports_streaming=True,
                    caption=f"🔥 ستريك متتالي لـ {record.current_streak} يوم!\nاحفظوا الفيديو وشاركوه بستوري 🎬",
                )
        return None
