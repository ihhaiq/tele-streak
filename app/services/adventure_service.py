from __future__ import annotations

import asyncio
import json
import logging
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
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyParameters,
)

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
        share_dir: Path | None = None,
        share_ttl_seconds: int = 900,
    ):
        self.bot = bot
        self.repository = repository
        self.data = AdventureRepository(repository.database)
        self.guests = guests
        self.renderer = StoryRenderer()
        self._music_uploads: dict[tuple[str, int], str] = {}
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
        music_file_id: str | None = None,
    ) -> tuple[Path, Path, str | None]:
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
            return cover, cover, None
        if kind not in {"video5", "video10"}:
            raise ValueError("unsupported story kind")

        duration = 5 if kind == "video5" else 10
        music_path = None
        if music_file_id:
            music_path = folder / "uploaded-audio"
            await self.bot.download(music_file_id, destination=music_path)
        job = asyncio.create_task(
            asyncio.to_thread(
                self.renderer.render,
                folder,
                days=record.current_streak,
                names=names,
                photos=photos,
                duration=duration,
                music_path=music_path,
            )
        )
        try:
            video = await asyncio.shield(job)
        except asyncio.CancelledError:
            try:
                await job
            finally:
                raise
        return video, cover, "الأغنية المضافة" if music_path else None

    async def begin_music_upload(self, token: str, user_id: int) -> str | None:
        request = await self.data.get_story_publish_request(token)
        if request is None:
            return None
        peer = await self.repository.get_owner_streak(
            request.owner_user_id, request.chat_id
        )
        if peer is None or user_id not in {
            request.owner_user_id,
            peer.peer_user_id or peer.chat_id,
        }:
            return None
        self._music_uploads[(request.business_connection_id, request.chat_id)] = token
        return request.business_connection_id

    async def handle_music_upload(self, message) -> bool:
        connection_id = message.business_connection_id
        if not connection_id or not (message.audio or message.voice):
            return False
        key = (connection_id, message.chat.id)
        token = self._music_uploads.pop(key, None)
        if not token:
            return False
        request = await self.data.get_story_publish_request(token)
        if request is None or message.from_user is None:
            return True
        peer = await self.repository.get_owner_streak(request.owner_user_id, request.chat_id)
        if peer is None or message.from_user.id not in {request.owner_user_id, peer.peer_user_id or peer.chat_id}:
            return True
        file_id = message.audio.file_id if message.audio else message.voice.file_id
        error = await self.prepare_story_preview(
            peer, request.owner_user_id, request.kind,
            music_file_id=file_id,
            music_uploader_id=message.from_user.id,
            reply_to_message_id=message.message_id,
        )
        if error:
            await self.bot.send_message(
                chat_id=message.chat.id,
                business_connection_id=connection_id,
                text=error,
            )
        return True

    async def delete_story_music(self, token: str, user_id: int) -> str | None:
        request = await self.data.get_story_publish_request(token)
        if request is None:
            return "انتهت صلاحية المعاينة."
        peer = await self.repository.get_owner_streak(request.owner_user_id, request.chat_id)
        if peer is None or user_id not in {request.owner_user_id, peer.peer_user_id or peer.chat_id}:
            return "فقط طرفا الستريك يگدرون يغيرون الأغنية."
        error = await self.prepare_story_preview(
            peer, request.owner_user_id, request.kind,
            music_file_id=None,
        )
        return error

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
        music_file_id: str | None = None,
        music_uploader_id: int | None = None,
    ) -> str | None:
        if kind not in {"image", "video5", "video10"}:
            return "نوع الستوري غير مدعوم."
        if record.current_streak < 1:
            return "كملوا أول يوم حتى نسوي ستوري 🔥"
        if self.share_dir is None:
            return "تعذر تجهيز مساحة مؤقتة لمعاينة الستوري."
        if self._story_slots.locked():
            return "Jake دا يجهز ستوريات، جرب بعد شوي 😆"

        async with self._story_slots:
            claim_timestamp = datetime.now(timezone.utc).timestamp()
            if not await self.data.claim_story(
                record.business_connection_id,
                record.chat_id,
                claim_timestamp,
            ):
                return "انتظر دقيقة بين كل ستوري والثاني 🎬"

            await asyncio.to_thread(
                self._cleanup_shared_files,
                self.share_dir,
                self.share_ttl_seconds + 300,
            )
            with TemporaryDirectory(prefix="streak-story-preview-") as directory:
                folder = Path(directory)
                try:
                    media, thumbnail, music_title = await self._render_story_assets(
                        record, owner, kind, folder, music_file_id
                    )
                except RuntimeError as error:
                    await self.data.release_story_claim(
                        record.business_connection_id,
                        record.chat_id,
                        claim_timestamp,
                    )
                    raise
                except Exception:
                    await self.data.release_story_claim(
                        record.business_connection_id,
                        record.chat_id,
                        claim_timestamp,
                    )
                    raise
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
                music_file_id=music_file_id,
                music_uploader_id=music_uploader_id,
            )
            await asyncio.to_thread(self._unlink_paths, old_paths)

            music_buttons = [
                InlineKeyboardButton(
                    text="🎵 تغيير الأغنية" if request.music_file_id else "🎵 أضف أغنية",
                    callback_data=f"story_music:{request.token}",
                )
            ]
            if request.music_file_id:
                music_buttons.append(
                    InlineKeyboardButton(
                        text="🗑 حذف الأغنية",
                        callback_data=f"story_music_delete:{request.token}",
                    )
                )
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="🚀 نشر الستوري",
                            callback_data=f"story_publish:{request.token}",
                        ),
                    ],
                    music_buttons,
                ]
            )
            caption = (
                f"🔥 ستريك متتالي لـ {record.current_streak} يوم!\n"
                + (f"🎵 {music_title}\n" if music_title else "")
                + "\nهاي معاينة الستوري. إذا عجبك اضغط «نشر الستوري»."
            )
            destination = {
                "chat_id": record.chat_id,
                "business_connection_id": record.business_connection_id,
                "caption": caption,
                "reply_markup": keyboard,
            }
            if reply_to_message_id is not None:
                destination["reply_parameters"] = ReplyParameters(
                    message_id=reply_to_message_id
                )

            try:
                if kind == "image":
                    await self.bot.send_photo(
                        **destination,
                        photo=FSInputFile(media_target, filename="streak-story.jpg"),
                    )
                else:
                    duration = 5 if kind == "video5" else 10
                    await self.bot.send_video(
                        **destination,
                        video=FSInputFile(media_target, filename="streak-story.mp4"),
                        duration=duration,
                        width=720,
                        height=1280,
                        supports_streaming=True,
                    )
            except Exception:
                paths = await self.data.delete_story_publish_request(request.token)
                await asyncio.to_thread(self._unlink_paths, paths)
                raise

            asyncio.create_task(
                self._expire_story_request(
                    request.token, self.share_ttl_seconds + 30
                ),
                name=f"story-preview-expire-{request.token}",
            )
        return None

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
        await asyncio.to_thread(
            self._unlink_paths,
            [request.media_path, request.thumbnail_path],
        )
        return StoryPublishResult("published", story_id)


    async def close(self) -> None:
        return None
