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
    def render_one_second_gif(source: Path, destination: Path) -> Path:
        """Convert a static source image into a visually static one-second GIF."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            frame = image.convert("RGBA")
            frame.save(
                destination,
                format="GIF",
                save_all=True,
                append_images=[frame.copy()],
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

            cache_key = f"animation:broken_notice:{digest}"
            cached = await self.repository.get_sticker_file_id(cache_key)
            if cached:
                return cached

            destination = self.output_dir / f"broken_notice_{digest}.gif"
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
