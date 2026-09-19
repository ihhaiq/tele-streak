from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import FSInputFile, InputSticker

from app.stickers.canvas import fit_to_canvas
from app.stickers.pack_builder import ReadyPackBuilder

logger = logging.getLogger(__name__)
PACK_SIZE = 120
PACK_ASSET_VERSION = 2
MAX_ATTEMPTS = 5


def sticker_set_name(bot_username: str, part: int = 1) -> str:
    safe = re.sub(r"[^a-z0-9_]", "", bot_username.lower())
    if not safe:
        raise ValueError("bot username cannot produce a sticker-set name")
    return f"jake_streak_shared_v{PACK_ASSET_VERSION}_{part}_by_{safe}"


@dataclass(frozen=True, slots=True)
class PackAsset:
    key: str
    path: Path
    emoji: str


class StickerPack:
    """Create resumable numbered Telegram packs and reuse their file IDs."""

    def __init__(self, bot: Bot, ready_dir: Path, *, owner_id: int | None = None, title: str = "Jake Streak") -> None:
        self.bot = bot
        self.ready_dir = ready_dir
        self.owner_id = owner_id
        self.title = title[:50]
        self._lock = asyncio.Lock()
        self._file_ids: dict[str, str] = {}
        self._sync_task: asyncio.Task[None] | None = None
        sheet = ready_dir.parents[2] / "jake" / "generated" / "poses_sheet.webp"
        self.builder = ReadyPackBuilder(sheet, ready_dir)
        self.normalized_dir = ready_dir.parent / f"normalized-v{PACK_ASSET_VERSION}"

    def _normalize_asset(self, key: str, source: Path) -> Path:
        """Build a centered upload copy without mutating reviewed source files."""
        self.normalized_dir.mkdir(parents=True, exist_ok=True)
        output = self.normalized_dir / f"{key}.webp"

        source_stat = source.stat()
        if output.is_file() and output.stat().st_mtime_ns >= source_stat.st_mtime_ns:
            return output

        with Image.open(source) as image:
            fit_to_canvas(image.convert("RGBA")).save(
                output,
                "WEBP",
                quality=92,
                method=6,
            )
        return output

    def _assets(self) -> list[PackAsset]:
        numbered = [
            PackAsset(
                str(day),
                self._normalize_asset(str(day), self.ready_dir / f"{day:03}.webp"),
                "🔥",
            )
            for day in range(1, 251)
        ]
        special = self.ready_dir.parent / "special"
        return numbered + [
            PackAsset(
                "warning",
                self._normalize_asset("warning", special / "warning.webp"),
                "⏰",
            ),
            PackAsset(
                "broken",
                self._normalize_asset("broken", special / "broken.webp"),
                "💔",
            ),
        ]

    @staticmethod
    def _input(asset: PackAsset) -> InputSticker:
        return InputSticker(sticker=FSInputFile(asset.path), format="static", emoji_list=[asset.emoji])

    async def _resolve_owner(self, connection_id: str | None, owner_id: int | None = None) -> int:
        if owner_id is not None:
            return owner_id
        if self.owner_id is not None:
            return self.owner_id
        raise RuntimeError("STICKER_SET_OWNER_ID must be configured for the developer")

    async def _retry(self, operation, *args, **kwargs):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await operation(*args, **kwargs)
            except TelegramRetryAfter as error:
                if attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(min(float(error.retry_after) + 0.25, 30.0))
            except (TelegramNetworkError, TelegramServerError):
                if attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
        raise RuntimeError("unreachable sticker-pack retry state")

    async def ensure(self, connection_id: str | None = None, owner_id: int | None = None) -> None:
        if len(self._file_ids) >= 252:
            return
        async with self._lock:
            if len(self._file_ids) >= 252:
                return
            await asyncio.to_thread(self.builder.ensure)
            assets = self._assets()
            if any(not asset.path.is_file() for asset in assets):
                raise RuntimeError("sticker pack has missing assets")
            me = await self.bot.get_me()
            if not me.username:
                raise RuntimeError("bot must have a username")
            owner_id = await self._resolve_owner(connection_id, owner_id)

            for part_index, offset in enumerate(range(0, len(assets), PACK_SIZE), start=1):
                part = assets[offset:offset + PACK_SIZE]
                name = sticker_set_name(me.username, part_index)
                try:
                    sticker_set = await self._retry(self.bot.get_sticker_set, name)
                except TelegramBadRequest:
                    await self._retry(
                        self.bot.create_new_sticker_set,
                        user_id=owner_id, name=name,
                        title=f"{self.title} {part_index}",
                        stickers=[self._input(part[0])], sticker_type="regular",
                    )
                    logger.info("STICKER_PACK_CREATED name=%s owner=%s", name, owner_id)
                    sticker_set = await self._retry(self.bot.get_sticker_set, name)

                uploaded = len(sticker_set.stickers)
                for asset in part[uploaded:]:
                    await self._retry(
                        self.bot.add_sticker_to_set,
                        user_id=owner_id, name=name, sticker=self._input(asset),
                    )
                    await asyncio.sleep(0.08)
                if uploaded < len(part):
                    logger.info("STICKER_PACK_SYNCED name=%s added=%s total=%s", name, len(part) - uploaded, len(part))
                    sticker_set = await self._retry(self.bot.get_sticker_set, name)

                for asset, sticker in zip(part, sticker_set.stickers, strict=False):
                    self._file_ids[asset.key] = sticker.file_id

    async def file_id(self, connection_id: str, days: int) -> str | None:
        await self.ensure(connection_id)
        return self._file_ids.get(str(days))

    async def special_file_id(self, connection_id: str, name: str) -> str | None:
        await self.ensure(connection_id)
        return self._file_ids.get(name)

    def cached_file_id(self, key: str) -> str | None:
        return self._file_ids.get(key)

    def start_sync(self, connection_id: str) -> None:
        if self._sync_task is not None and not self._sync_task.done():
            return
        self._sync_task = asyncio.create_task(
            self._sync(connection_id),
            name="sticker-pack-sync",
        )

    def start_sync_for_owner(self, owner_id: int) -> None:
        if self._sync_task is not None and not self._sync_task.done():
            return
        self._sync_task = asyncio.create_task(
            self._sync_for_owner(owner_id),
            name="sticker-pack-owner-sync",
        )

    async def _sync(self, connection_id: str) -> None:
        try:
            await self.ensure(connection_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("STICKER_PACK_SYNC_FAILED connection=%s", connection_id)

    async def _sync_for_owner(self, owner_id: int) -> None:
        try:
            await self.ensure(owner_id=owner_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("STICKER_PACK_OWNER_SYNC_FAILED owner=%s", owner_id)

    def pack_names(self, bot_username: str) -> list[str]:
        return [sticker_set_name(bot_username, part) for part in range(1, 4)]
