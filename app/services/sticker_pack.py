from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter, TelegramServerError
from aiogram.types import FSInputFile, InputSticker

from app.stickers.pack_builder import ReadyPackBuilder

logger = logging.getLogger(__name__)
PACK_SIZE = 120
MAX_ATTEMPTS = 5


def sticker_set_name(bot_username: str, part: int = 1) -> str:
    safe = re.sub(r"[^a-z0-9_]", "", bot_username.lower())
    if not safe:
        raise ValueError("bot username cannot produce a sticker-set name")
    return f"jake_streak_{part}_by_{safe}"


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
        sheet = ready_dir.parents[2] / "jake" / "generated" / "poses_sheet.webp"
        self.builder = ReadyPackBuilder(sheet, ready_dir)

    def _assets(self) -> list[PackAsset]:
        numbered = [PackAsset(str(day), self.ready_dir / f"{day:03}.webp", "🔥") for day in range(1, 251)]
        special = self.ready_dir.parent / "special"
        return numbered + [
            PackAsset("warning", special / "warning.webp", "⏰"),
            PackAsset("broken", special / "broken.webp", "💔"),
        ]

    @staticmethod
    def _input(asset: PackAsset) -> InputSticker:
        return InputSticker(sticker=FSInputFile(asset.path), format="static", emoji_list=[asset.emoji])

    async def _resolve_owner(self, connection_id: str) -> int:
        if self.owner_id is not None:
            return self.owner_id
        return (await self.bot.get_business_connection(connection_id)).user.id

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

    async def ensure(self, connection_id: str) -> None:
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
            owner_id = await self._resolve_owner(connection_id)

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
