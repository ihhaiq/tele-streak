from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile, InputSticker

logger = logging.getLogger(__name__)


def sticker_set_name(bot_username: str) -> str:
    """Return a deterministic Bot API-compatible sticker-set name."""
    safe_username = re.sub(r"[^a-z0-9_]", "", bot_username.lower())
    if not safe_username:
        raise ValueError("bot username cannot produce a sticker-set name")
    return f"jake_streak_by_{safe_username}"[:64]


class StickerPack:
    """Create the numbered Telegram sticker set once and reuse its file IDs."""

    def __init__(
        self,
        bot: Bot,
        ready_dir: Path,
        *,
        owner_id: int | None = None,
        title: str = "Jake Streak",
    ) -> None:
        self.bot = bot
        self.ready_dir = ready_dir
        self.owner_id = owner_id
        self.title = title[:64]
        self._lock = asyncio.Lock()
        self._file_ids: list[str] = []

    def _assets(self) -> list[Path]:
        return sorted(
            (path for path in self.ready_dir.glob("[0-9][0-9][0-9].webp")),
            key=lambda path: int(path.stem),
        )

    @staticmethod
    def _input(path: Path) -> InputSticker:
        return InputSticker(
            sticker=FSInputFile(path),
            format="static",
            emoji_list=["🔥"],
        )

    async def _resolve_owner(self, connection_id: str) -> int:
        if self.owner_id is not None:
            return self.owner_id
        connection = await self.bot.get_business_connection(connection_id)
        return connection.user.id

    async def ensure(self, connection_id: str) -> None:
        if self._file_ids:
            return

        async with self._lock:
            if self._file_ids:
                return
            assets = self._assets()
            if not assets:
                raise RuntimeError(f"no ready stickers found in {self.ready_dir}")

            me = await self.bot.get_me()
            if not me.username:
                raise RuntimeError("bot must have a username to own a sticker set")
            name = sticker_set_name(me.username)
            owner_id = await self._resolve_owner(connection_id)

            try:
                sticker_set = await self.bot.get_sticker_set(name)
            except TelegramBadRequest:
                await self.bot.create_new_sticker_set(
                    user_id=owner_id,
                    name=name,
                    title=self.title,
                    stickers=[self._input(assets[0])],
                    sticker_type="regular",
                )
                logger.info("STICKER_PACK_CREATED name=%s owner=%s", name, owner_id)
                sticker_set = await self.bot.get_sticker_set(name)

            uploaded = len(sticker_set.stickers)
            for path in assets[uploaded:]:
                await self.bot.add_sticker_to_set(
                    user_id=owner_id,
                    name=name,
                    sticker=self._input(path),
                )

            if uploaded < len(assets):
                logger.info(
                    "STICKER_PACK_SYNCED name=%s added=%s total=%s",
                    name,
                    len(assets) - uploaded,
                    len(assets),
                )
                sticker_set = await self.bot.get_sticker_set(name)

            self._file_ids = [sticker.file_id for sticker in sticker_set.stickers]

    async def file_id(self, connection_id: str, days: int) -> str | None:
        await self.ensure(connection_id)
        index = days - 1
        return self._file_ids[index] if 0 <= index < len(self._file_ids) else None
