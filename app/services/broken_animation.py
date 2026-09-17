from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import FSInputFile
from PIL import Image

from app.database.repository import Repository

logger = logging.getLogger(__name__)

GIF_RENDER_VERSION = "v2"


class BrokenAnimationService:
    """Build and cache the one-second GIF used in the broken-streak rich message."""

    def __init__(
        self,
        bot: Bot,
        repository: Repository,
        source_path: Path,
        output_dir: Path,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.source_path = source_path
        self.output_dir = output_dir
        self._lock = asyncio.Lock()

    def _source_digest(self) -> str:
        return hashlib.sha256(self.source_path.read_bytes()).hexdigest()[:16]

    @staticmethod
    def _make_distinct_second_frame(frame: Image.Image) -> Image.Image:
        """Keep the image visually static while forcing a real second GIF frame.

        Pillow collapses byte-identical frames into one frame, which Telegram can
        treat as a static image instead of an animation. Change one visible pixel
        only; the difference is imperceptible at sticker scale but keeps two real
        frames in the encoded GIF.
        """
        second = frame.copy()
        pixels = second.load()
        width, height = second.size

        target: tuple[int, int] | None = None
        for y in range(height):
            for x in range(width):
                red, green, blue, alpha = pixels[x, y]
                if alpha > 0:
                    target = (x, y)
                    break
            if target is not None:
                break

        if target is None:
            target = (0, 0)

        x, y = target
        red, green, blue, alpha = pixels[x, y]
        pixels[x, y] = (
            255 - red,
            255 - green,
            255 - blue,
            max(alpha, 1),
        )
        return second

    @staticmethod
    def render_one_second_gif(source: Path, destination: Path) -> Path:
        """Convert the static source into a visually static, real two-frame GIF."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            first = image.convert("RGBA")
            second = BrokenAnimationService._make_distinct_second_frame(first)
            first.save(
                destination,
                format="GIF",
                save_all=True,
                append_images=[second],
                duration=[500, 500],
                loop=0,
                disposal=2,
                optimize=False,
            )
        return destination

    async def ensure_file_id(self, connection_id: str, chat_id: int) -> str | None:
        """Return a Telegram animation file_id, uploading a temporary GIF once."""
        async with self._lock:
            try:
                digest = self._source_digest()
            except OSError:
                logger.exception("BROKEN_GIF_SOURCE_UNAVAILABLE path=%s", self.source_path)
                return None

            # Include the renderer version so a previously cached one-frame GIF
            # can never mask a renderer fix.
            cache_key = f"animation:broken_notice:{GIF_RENDER_VERSION}:{digest}"
            cached = await self.repository.get_sticker_file_id(cache_key)
            if cached:
                return cached

            destination = self.output_dir / f"broken_notice_{GIF_RENDER_VERSION}_{digest}.gif"
            try:
                if not destination.exists():
                    await asyncio.to_thread(
                        self.render_one_second_gif,
                        self.source_path,
                        destination,
                    )
            except Exception:
                logger.exception(
                    "BROKEN_GIF_RENDER_FAILED source=%s destination=%s",
                    self.source_path,
                    destination,
                )
                return None

            temporary_message_id: int | None = None
            try:
                sent = await self.bot.send_animation(
                    chat_id=chat_id,
                    business_connection_id=connection_id,
                    animation=FSInputFile(destination, filename="broken_streak.gif"),
                    duration=1,
                    disable_notification=True,
                )
                temporary_message_id = sent.message_id
                if sent.animation is None:
                    logger.warning(
                        "BROKEN_GIF_UPLOAD_NO_ANIMATION connection=%s chat=%s",
                        connection_id,
                        chat_id,
                    )
                    return None
                file_id = sent.animation.file_id
                await self.repository.set_sticker_file_id(cache_key, file_id)
                logger.info(
                    "BROKEN_GIF_READY connection=%s chat=%s file_unique_id=%s duration=%s",
                    connection_id,
                    chat_id,
                    sent.animation.file_unique_id,
                    sent.animation.duration,
                )
                return file_id
            except Exception:
                logger.exception(
                    "BROKEN_GIF_UPLOAD_FAILED connection=%s chat=%s",
                    connection_id,
                    chat_id,
                )
                return None
            finally:
                if temporary_message_id is not None:
                    try:
                        await self.bot.delete_business_messages(
                            business_connection_id=connection_id,
                            message_ids=[temporary_message_id],
                        )
                    except (TelegramBadRequest, TelegramForbiddenError):
                        logger.info(
                            "BROKEN_GIF_TEMP_DELETE_SKIPPED connection=%s chat=%s message=%s",
                            connection_id,
                            chat_id,
                            temporary_message_id,
                        )
