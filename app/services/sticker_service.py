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
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message, ReplyParameters

from app.database.repository import Repository
from app.keyboards.streak import revive_streak_keyboard, streak_keyboard
from app.services.rich_status import build_streak_fallback_text, build_streak_rich_message
from app.services.streak_messages import BROKEN_NOTICE_TEXT, build_broken_notice_rich_message
from app.services.sticker_pack import StickerPack

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
        *,
        message_effect_id: str | None = None,
        sticker_set_owner_id: int | None = None,
        sticker_set_title: str = "Jake Streak",
    ):
        self.bot = bot
        self.repository = repository
        self.renderer = renderer
        self.ready_stickers_dir = ready_stickers_dir
        self.message_effect_id = message_effect_id
        self.pack = StickerPack(
            bot,
            ready_stickers_dir,
            owner_id=sticker_set_owner_id,
            title=sticker_set_title,
        )

    async def send_notice_text(
        self,
        *,
        connection_id: str,
        chat_id: int,
        text: str,
    ) -> None:
        await self.bot.send_message(
            chat_id=chat_id,
            business_connection_id=connection_id,
            text=text,
        )

    async def send_broken_notice(
        self,
        *,
        connection_id: str,
        chat_id: int,
    ) -> Message:
        try:
            return await self.bot.send_rich_message(
                chat_id=chat_id,
                business_connection_id=connection_id,
                rich_message=build_broken_notice_rich_message(),
            )
        except TelegramBadRequest as error:
            logger.warning("BROKEN_NOTICE_RICH_REJECTED error=%s", error)
            return await self.bot.send_message(
                chat_id=chat_id,
                business_connection_id=connection_id,
                text=BROKEN_NOTICE_TEXT,
            )

    async def prepare_pack_for_owner(self, owner_id: int) -> None:
        """Synchronize the complete pack for an explicitly selected owner."""
        await self.pack.ensure(owner_id=owner_id)

    async def send_status(
        self,
        *,
        connection_id: str,
        chat_id: int,
        current: int,
        longest: int,
        completed_days: int,
        break_count: int,
        freeze_count: int,
        last_completed_day: str | None,
        timezone_name: str | None = None,
    ) -> None:
        streak = await self.repository.get_streak(connection_id, chat_id)
        settings_token = await self.repository.ensure_streak_settings_token(
            connection_id,
            chat_id,
        )
        streak_mode = streak.streak_mode if streak is not None else "message"
        rich_message = build_streak_rich_message(
            current=current,
            longest=longest,
            completed_days=completed_days,
            break_count=break_count,
            freeze_count=freeze_count,
            last_completed_day=last_completed_day,
            timezone_name=timezone_name,
            streak_mode=streak_mode,
            settings_token=settings_token,
        )
        kwargs = dict(
            chat_id=chat_id,
            business_connection_id=connection_id,
            rich_message=rich_message,
        )
        try:
            await self.bot.send_rich_message(
                **kwargs,
                message_effect_id=self.message_effect_id,
            )
            return
        except TelegramBadRequest as error:
            if self.message_effect_id:
                logger.warning(
                    "STREAK_RICH_EFFECT_REJECTED error=%s",
                    error,
                )
                try:
                    await self.bot.send_rich_message(**kwargs)
                    return
                except TelegramBadRequest as rich_error:
                    logger.warning(
                        "STREAK_RICH_REJECTED error=%s",
                        rich_error,
                    )
            else:
                logger.warning(
                    "STREAK_RICH_REJECTED error=%s",
                    error,
                )

        await self.bot.send_message(
            chat_id=chat_id,
            business_connection_id=connection_id,
            text=build_streak_fallback_text(
                current=current,
                longest=longest,
                completed_days=completed_days,
                break_count=break_count,
                freeze_count=freeze_count,
                last_completed_day=last_completed_day,
                timezone_name=timezone_name,
                streak_mode=streak_mode,
            ),
        )

    async def _send_sticker_once(
        self,
        *,
        connection_id: str,
        chat_id: int,
        sticker: str | FSInputFile,
        days: int | None,
        with_effect: bool,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to_message_id: int | None = None,
    ) -> Message:
        kwargs = dict(
            chat_id=chat_id,
            sticker=sticker,
            business_connection_id=connection_id,
            reply_markup=reply_markup or (streak_keyboard(days) if days else None),
            reply_parameters=(
                ReplyParameters(message_id=reply_to_message_id)
                if reply_to_message_id is not None
                else None
            ),
        )
        try:
            return await self.bot.send_sticker(
                **kwargs,
                message_effect_id=self.message_effect_id if with_effect else None,
            )
        except TelegramBadRequest as error:
            if not (with_effect and self.message_effect_id):
                raise
            logger.warning("Message effect rejected; sending sticker without it: %s", error)
            return await self.bot.send_sticker(**kwargs)

    async def _send_sticker(
        self,
        *,
        connection_id: str,
        chat_id: int,
        sticker: str | FSInputFile,
        days: int | None,
        with_effect: bool = False,
        reply_markup: InlineKeyboardMarkup | None = None,
        reply_to_message_id: int | None = None,
    ) -> Message:
        for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
            try:
                return await self._send_sticker_once(
                    connection_id=connection_id,
                    chat_id=chat_id,
                    sticker=sticker,
                    days=days,
                    with_effect=with_effect,
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
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

    async def send_special(
        self,
        *,
        connection_id: str,
        chat_id: int,
        name: str,
        revive_available: bool = False,
        reply_to_message_id: int | None = None,
    ) -> None:
        if name not in {"warning", "broken"}:
            raise ValueError("unknown special sticker")
        sticker_key = f"special:{name}"
        reply_markup = (
            revive_streak_keyboard()
            if name == "broken" and revive_available
            else None
        )
        pack_file_id = self.pack.cached_file_id(name)
        if pack_file_id:
            await self._send_sticker(
                connection_id=connection_id,
                chat_id=chat_id,
                sticker=pack_file_id,
                days=None,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
            return
        self.pack.start_sync(connection_id)
        cached_file_id = await self.repository.get_sticker_file_id(sticker_key)
        sent: Message | None = None

        if cached_file_id:
            try:
                sent = await self._send_sticker(
                    connection_id=connection_id,
                    chat_id=chat_id,
                    sticker=cached_file_id,
                    days=None,
                    reply_markup=reply_markup,
                    reply_to_message_id=reply_to_message_id,
                )
            except TelegramBadRequest:
                logger.warning(
                    "Cached special sticker rejected; uploading: key=%s",
                    sticker_key,
                )

        if sent is None:
            path = self.ready_stickers_dir.parent / "special" / f"{name}.webp"
            sent = await self._send_sticker(
                connection_id=connection_id,
                chat_id=chat_id,
                sticker=FSInputFile(path),
                days=None,
                reply_markup=reply_markup,
                reply_to_message_id=reply_to_message_id,
            )
            if sent.sticker:
                await self.repository.set_sticker_file_id(
                    sticker_key,
                    sent.sticker.file_id,
                )

    async def send_success(
        self,
        *,
        connection_id: str,
        chat_id: int,
        pose: str,
        days: int,
    ) -> None:
        sent: Message | None = None

        pack_file_id = self.pack.cached_file_id(str(days))
        if pack_file_id:
            sent = await self._send_sticker(
                connection_id=connection_id,
                chat_id=chat_id,
                sticker=pack_file_id,
                days=days,
                with_effect=True,
            )
        else:
            self.pack.start_sync(connection_id)

        sticker_key = f"streak:{days}"
        cached_file_id = await self.repository.get_sticker_file_id(sticker_key)
        if sent is None and cached_file_id:
            try:
                sent = await self._send_sticker(
                    connection_id=connection_id,
                    chat_id=chat_id,
                    sticker=cached_file_id,
                    days=days,
                    with_effect=True,
                )
            except TelegramBadRequest:
                logger.warning(
                    "Cached sticker file_id rejected; uploading again: key=%s",
                    sticker_key,
                )

        if sent is None:
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
                with_effect=True,
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
