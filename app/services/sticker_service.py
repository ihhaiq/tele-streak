from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.types import FSInputFile, Message

from app.database.repository import Repository
from app.keyboards.streak import streak_keyboard

logger = logging.getLogger(__name__)
MAX_SEND_ATTEMPTS = 3


class Renderer(Protocol):
    def render(self, pose_id: str, days: int) -> Path: ...


def resolve_sticker_path(
    ready_stickers_dir: Path,
    renderer: Renderer,
    pose_id: str,
    days: int,
) -> Path:
    if days < 1:
        raise ValueError("days must be positive")
    ready = ready_stickers_dir / f"{days:03}.webp"
    return ready if ready.is_file() else renderer.render(pose_id, days)


class StickerService:
    def __init__(
        self,
        bot: Bot,
        repository: Repository,
        renderer: Renderer,
        ready_stickers_dir: Path,
    ):
        self.bot = bot
        self.repository = repository
        self.renderer = renderer
        self.ready_stickers_dir = ready_stickers_dir

    async def send_status(
        self,
        *,
        connection_id: str,
        chat_id: int,
        current: int,
        longest: int,
        last_completed_day: str | None,
    ) -> None:
        last_day = last_completed_day or "لا يوجد"
        await self.bot.send_message(
            chat_id=chat_id,
            business_connection_id=connection_id,
            text=(
                "🔥 حالة الستريك\n"
                f"الحالي: {current}\n"
                f"الأعلى: {longest}\n"
                f"آخر يوم مكتمل: {last_day}"
            ),
        )

    async def _send_sticker(
        self,
        *,
        connection_id: str,
        chat_id: int,
        sticker: str | FSInputFile,
        days: int,
    ) -> Message:
        for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
            try:
                return await self.bot.send_sticker(
                    chat_id=chat_id,
                    sticker=sticker,
                    business_connection_id=connection_id,
                    reply_markup=streak_keyboard(days),
                )
            except TelegramRetryAfter as error:
                if attempt == MAX_SEND_ATTEMPTS:
                    raise
                await asyncio.sleep(min(float(error.retry_after), 10.0))
            except (TelegramNetworkError, TelegramServerError):
                if attempt == MAX_SEND_ATTEMPTS:
                    raise
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
        raise RuntimeError("unreachable sticker retry state")

    async def send_success(
        self,
        *,
        connection_id: str,
        chat_id: int,
        pose: str,
        days: int,
    ) -> None:
        sticker_key = f"streak:{days}"
        cached_file_id = await self.repository.get_sticker_file_id(sticker_key)

        sent: Message
        if cached_file_id:
            try:
                sent = await self._send_sticker(
                    connection_id=connection_id,
                    chat_id=chat_id,
                    sticker=cached_file_id,
                    days=days,
                )
            except TelegramBadRequest:
                logger.warning(
                    "Cached sticker file_id rejected; uploading again: key=%s",
                    sticker_key,
                )
                cached_file_id = None

        if not cached_file_id:
            path = resolve_sticker_path(
                self.ready_stickers_dir,
                self.renderer,
                pose,
                days,
            )
            sent = await self._send_sticker(
                connection_id=connection_id,
                chat_id=chat_id,
                sticker=FSInputFile(path),
                days=days,
            )
            if sent.sticker:
                await self.repository.set_sticker_file_id(
                    sticker_key,
                    sent.sticker.file_id,
                )

        await self.repository.set_success_message_id(
            connection_id,
            chat_id,
            sent.message_id,
        )
