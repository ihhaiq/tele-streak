from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo

import aiohttp
from aiogram.exceptions import TelegramAPIError
from aiogram.types import FSInputFile

from app.adventures.views import navigation, progress_text
from app.database.adventure_repository import AdventureRepository
from app.story.renderer import StoryRenderer, write_celebration

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StoryPublishResult:
    status: str
    story_id: int | None = None


class AdventureService:
    def __init__(
        self,
        bot,
        repository,
        guests,
        *,
        music_path: Path | None = None,
        public_base_url: str | None = None,
        share_dir: Path | None = None,
        share_ttl_seconds: int = 900,
    ):
        self.bot = bot
        self.repository = repository
        self.data = AdventureRepository(repository.database)
        self.guests = guests
        self.renderer = StoryRenderer(music_path)
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.share_dir = Path(share_dir) if share_dir else None
        if self.share_dir is not None:
            self.share_dir.mkdir(parents=True, exist_ok=True)
        self.share_ttl_seconds = max(60, min(int(share_ttl_seconds), 3600))
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
            logger.info("STORY_AVATAR_UNAVAILABLE user=%s", user_id)
        return name, None

    async def _render_story_assets(
        self,
        record,
        owner: int,
        kind: str,
        folder: Path,
    ) -> tuple[Path, Path]:
        profile, _ = await self.snapshot(
            record.business_connection_id, record.chat_id
        )
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
        names = (first[0], second[0])
        photos = (first[1], second[1])
        cover = await asyncio.to_thread(
            self.renderer.render_image,
            folder,
            days=record.current_streak,
            names=names,
            photos=photos,
        )
        if kind == "image":
            return cover, cover
        if kind not in {"video5", "video10"}:
            raise ValueError("unsupported story kind")
        duration = 5 if kind == "video5" else 10
        job = asyncio.create_task(
            asyncio.to_thread(
                self.renderer.render,
                folder,
                days=record.current_streak,
                names=names,
                photos=photos,
                duration=duration,
            )
        )
        try:
            video = await asyncio.shield(job)
        except asyncio.CancelledError:
            try:
                await job
            finally:
                raise
        return video, cover

    @staticmethod
    def _unlink_paths(paths) -> None:
        for raw in set(paths):
            if not raw:
                continue
            try:
                Path(raw).unlink(missing_ok=True)
            except OSError:
                logger.debug("STORY_SHARE_DELETE_FAILED path=%s", raw)

    @staticmethod
    def _cleanup_shared_files(folder: Path, max_age_seconds: int) -> None:
        cutoff = time.time() - max_age_seconds
        for item in folder.glob("*"):
            try:
                if item.is_file() and item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
            except OSError:
                logger.debug("STORY_SHARE_CLEANUP_FAILED path=%s", item)

    async def _expire_story_request(self, token: str, delay: int) -> None:
        await asyncio.sleep(max(60, delay))
        request = await self.data.get_story_publish_request(token, allow_expired=True)
        if request is None or request.expires_at > time.time():
            return
        paths = await self.data.delete_story_publish_request(token)
        await asyncio.to_thread(self._unlink_paths, paths)

    async def prepare_story_preview(
        self,
        record,
        owner: int,
        kind: str,
        *,
        reply_to_message_id: int | None = None,
    ) -> str | None:
        if kind not in {"image", "video5", "video10"}:
            return "نوع الستوري غير مدعوم."
        if record.current_streak < 1:
            return "كملوا أول يوم حتى نسوي ستوري 🔥"
        if not self.public_base_url or self.share_dir is None:
            return "ميزة المعاينة تحتاج Public Domain للخدمة على Railway."
        if self._story_slots.locked():
            return "Jake دا يجهز ستوريات، جرب بعد شوي 😆"

        async with self._story_slots:
            if not await self.data.claim_story(
                record.business_connection_id,
                record.chat_id,
                datetime.now(timezone.utc).timestamp(),
            ):
                return "انتظر دقيقة بين كل ستوري والثاني 🎬"

            await asyncio.to_thread(
                self._cleanup_shared_files,
                self.share_dir,
                self.share_ttl_seconds + 300,
            )
            with TemporaryDirectory(prefix="streak-story-preview-") as directory:
                folder = Path(directory)
                media, thumbnail = await self._render_story_assets(
                    record, owner, kind, folder
                )
                asset_id = secrets.token_hex(10)
                media_suffix = ".jpg" if kind == "image" else ".mp4"
                media_target = self.share_dir / f"{asset_id}{media_suffix}"
                thumb_target = (
                    media_target
                    if kind == "image"
                    else self.share_dir / f"{asset_id}-thumb.jpg"
                )
                await asyncio.to_thread(shutil.copyfile, media, media_target)
                if kind != "image":
                    await asyncio.to_thread(shutil.copyfile, thumbnail, thumb_target)

            request, old_paths = await self.data.create_story_publish_request(
                connection_id=record.business_connection_id,
                chat_id=record.chat_id,
                owner_user_id=owner,
                kind=kind,
                media_path=str(media_target),
                thumbnail_path=str(thumb_target),
                days=record.current_streak,
                ttl_seconds=self.share_ttl_seconds,
            )
            await asyncio.to_thread(self._unlink_paths, old_paths)

            summoned = await self.guests.summon(
                event="story_preview",
                connection_id=record.business_connection_id,
                chat_id=record.chat_id,
                reply_to_message_id=reply_to_message_id,
                ttl_seconds=120,
                payload=request.token,
            )
            if not summoned:
                paths = await self.data.delete_story_publish_request(request.token)
                await asyncio.to_thread(self._unlink_paths, paths)
                return "تعذر إرسال معاينة الستوري بوضع الضيف."

            asyncio.create_task(
                self._expire_story_request(
                    request.token, self.share_ttl_seconds + 30
                ),
                name=f"story-preview-expire-{request.token}",
            )
        return None

    async def story_preview(self, token: str, connection_id: str, chat_id: int):
        request = await self.data.get_story_publish_request(token)
        if (
            request is None
            or request.business_connection_id != connection_id
            or request.chat_id != chat_id
        ):
            return None
        return {
            "token": request.token,
            "kind": request.kind,
            "days": request.days,
            "media_url": f"{self.public_base_url}/story/media/{request.token}",
            "thumbnail_url": f"{self.public_base_url}/story/thumb/{request.token}",
        }

    async def story_preview_asset(
        self, token: str, *, thumbnail: bool = False
    ) -> Path | None:
        request = await self.data.get_story_publish_request(token)
        if request is None:
            return None
        path = Path(request.thumbnail_path if thumbnail else request.media_path)
        return path if path.is_file() else None

    async def _post_story(self, request) -> int:
        path = Path(request.media_path)
        if not path.is_file():
            raise FileNotFoundError("story media is missing")

        if request.kind == "image":
            content = {"type": "photo", "photo": "attach://story_file"}
            mime = "image/jpeg"
            filename = "streak-story.jpg"
        else:
            duration = 5 if request.kind == "video5" else 10
            content = {
                "type": "video",
                "video": "attach://story_file",
                "duration": duration,
                "is_animation": False,
            }
            mime = "video/mp4"
            filename = "streak-story.mp4"

        form = aiohttp.FormData()
        form.add_field("business_connection_id", request.business_connection_id)
        form.add_field("content", json.dumps(content, separators=(",", ":")))
        form.add_field("active_period", str(24 * 3600))
        form.add_field(
            "caption",
            f"🔥 ستريك متتالي لـ {request.days} يوم!",
        )
        with path.open("rb") as media:
            form.add_field(
                "story_file",
                media,
                filename=filename,
                content_type=mime,
            )
            timeout = aiohttp.ClientTimeout(total=120)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"https://api.telegram.org/bot{self.bot.token}/postStory",
                    data=form,
                ) as response:
                    payload = await response.json(content_type=None)

        if not payload.get("ok"):
            description = str(payload.get("description") or "Telegram rejected story")
            raise RuntimeError(description)
        result = payload.get("result") or {}
        story_id = int(result.get("id") or 0)
        if story_id <= 0:
            raise RuntimeError("Telegram returned story without an id")
        return story_id

    async def publish_story(
        self,
        token: str,
        user_id: int,
    ) -> StoryPublishResult:
        status, request = await self.data.claim_story_publish(token, user_id)
        if status != "ready" or request is None:
            return StoryPublishResult(status)

        try:
            connection = await self.bot.get_business_connection(
                request.business_connection_id
            )
            rights = getattr(connection, "rights", None)
            if (
                not getattr(connection, "is_enabled", False)
                or rights is None
                or not bool(getattr(rights, "can_manage_stories", False))
            ):
                await self.data.release_story_publish(token)
                return StoryPublishResult("permission")

            story_id = await self._post_story(request)
        except Exception:
            await self.data.release_story_publish(token)
            logger.exception(
                "STORY_BUSINESS_PUBLISH_FAILED connection=%s chat=%s kind=%s",
                request.business_connection_id,
                request.chat_id,
                request.kind,
            )
            return StoryPublishResult("failed")

        await self.data.complete_story_publish(token, story_id)
        return StoryPublishResult("published", story_id)

    async def send_story_image(self, record, owner: int) -> str | None:
        if record.current_streak < 1:
            return "كملوا أول يوم حتى نسوي ستوري 🔥"
        if self._story_slots.locked():
            return "Jake دا يجهز ستوريات، جرب بعد شوي 😆"
        async with self._story_slots:
            with TemporaryDirectory(prefix="streak-story-") as directory:
                media, _ = await self._render_story_assets(
                    record, owner, "image", Path(directory)
                )
                await self.bot.send_photo(
                    chat_id=record.chat_id,
                    business_connection_id=record.business_connection_id,
                    photo=FSInputFile(media, filename="streak-story.jpg"),
                    caption=(
                        f"🔥 ستريك متتالي لـ {record.current_streak} يوم!\n"
                        "معاينة الستوري 🖼️"
                    ),
                )
        return None

    async def send_story(self, record, owner: int, duration: int) -> str | None:
        if duration not in {5, 10}:
            return "مدة الفيديو غير مدعومة."
        if record.current_streak < 1:
            return "كملوا أول يوم حتى نسوي ستوري 🔥"
        if self._story_slots.locked():
            return "Jake دا يجهز ستوريات، جرب بعد شوي 😆"
        async with self._story_slots:
            with TemporaryDirectory(prefix="streak-story-") as directory:
                media, _ = await self._render_story_assets(
                    record, owner, f"video{duration}", Path(directory)
                )
                await self.bot.send_video(
                    chat_id=record.chat_id,
                    business_connection_id=record.business_connection_id,
                    video=FSInputFile(media, filename="streak-story.mp4"),
                    duration=duration,
                    width=720,
                    height=1280,
                    supports_streaming=True,
                    caption=(
                        f"🔥 ستريك متتالي لـ {record.current_streak} يوم!\n"
                        "معاينة الستوري 🎬"
                    ),
                )
        return None
