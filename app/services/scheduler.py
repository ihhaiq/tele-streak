from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.database.repository import Repository
from app.services.guest_delivery import GuestDeliveryService
from app.services.sticker_service import StickerService
from app.services.streak_messages import BROKEN_NOTICE_TEXT

logger = logging.getLogger(__name__)


class StreakScheduler:
    def __init__(
        self,
        repository: Repository,
        stickers: StickerService,
        guests: GuestDeliveryService,
        *,
        interval_seconds: int = 300,
        warning_hour: int = 22,
    ):
        self.repository = repository
        self.stickers = stickers
        self.guests = guests
        self.interval_seconds = interval_seconds
        self.warning_hour = warning_hour

    async def run_forever(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("STREAK_SCHEDULER_FAILED")
            await asyncio.sleep(self.interval_seconds)

    async def run_once(self) -> None:
        rows = await self.repository.list_monitorable_streaks()
        for streak, timezone_name in rows:
            try:
                timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError:
                logger.error(
                    "INVALID_TIMEZONE connection=%s timezone=%s",
                    streak.business_connection_id,
                    timezone_name,
                )
                continue

            local_now = datetime.now(timezone)
            today_date = local_now.date()
            today = today_date.isoformat()
            yesterday_date = today_date - timedelta(days=1)
            yesterday = yesterday_date.isoformat()
            day_before = (yesterday_date - timedelta(days=1)).isoformat()

            if (
                local_now.hour >= self.warning_hour
                and streak.last_completed_day != today
                and streak.last_warning_day != today
            ):
                claimed = await self.repository.claim_warning(
                    streak.business_connection_id,
                    streak.chat_id,
                    today,
                )
                if claimed:
                    sticker_sent = await self.guests.summon(
                        event="warning_sticker",
                        connection_id=streak.business_connection_id,
                        chat_id=streak.chat_id,
                    )
                    if not sticker_sent:
                        await self.stickers.send_special(
                            connection_id=streak.business_connection_id,
                            chat_id=streak.chat_id,
                            name="warning",
                        )

                    owner_missing = streak.owner_sent_day != today
                    peer_missing = streak.peer_sent_day != today
                    if owner_missing and peer_missing:
                        missing = "أنتما لم ترسلا اليوم"
                    elif owner_missing:
                        missing = "صاحب الحساب لم يرسل اليوم"
                    else:
                        missing = "الطرف الثاني لم يرسل اليوم"

                    notice_sent = await self.guests.summon(
                        event="warning_notice",
                        connection_id=streak.business_connection_id,
                        chat_id=streak.chat_id,
                    )
                    if not notice_sent:
                        await self.stickers.send_notice_text(
                            connection_id=streak.business_connection_id,
                            chat_id=streak.chat_id,
                            text=f"⏰ بقي أقل من ساعتين. {missing} وقد ينقطع الستريك.",
                        )
                    logger.info(
                        "WARNING_SENT connection=%s chat=%s guest_sticker=%s guest_notice=%s",
                        streak.business_connection_id,
                        streak.chat_id,
                        sticker_sent,
                        notice_sent,
                    )

            if (
                streak.last_completed_day is not None
                and streak.last_completed_day < yesterday
            ):
                result = await self.repository.process_missed_day(
                    connection_id=streak.business_connection_id,
                    chat_id=streak.chat_id,
                    today=today,
                    missed_day=yesterday,
                    day_before_missed=day_before,
                )
                if result == "broken":
                    sticker_sent = await self.guests.summon(
                        event="broken",
                        connection_id=streak.business_connection_id,
                        chat_id=streak.chat_id,
                    )
                    if not sticker_sent:
                        await self.stickers.send_special(
                            connection_id=streak.business_connection_id,
                            chat_id=streak.chat_id,
                            name="broken",
                            revive_available=False,
                        )

                    notice_sent = await self.guests.summon(
                        event="broken_notice",
                        connection_id=streak.business_connection_id,
                        chat_id=streak.chat_id,
                    )
                    if not notice_sent:
                        await self.stickers.send_notice_text(
                            connection_id=streak.business_connection_id,
                            chat_id=streak.chat_id,
                            text=BROKEN_NOTICE_TEXT,
                        )

                    logger.info(
                        "STREAK_BROKEN connection=%s chat=%s guest_sticker=%s guest_notice=%s",
                        streak.business_connection_id,
                        streak.chat_id,
                        sticker_sent,
                        notice_sent,
                    )
                elif result == "frozen":
                    logger.info(
                        "STREAK_PROTECTION_USED connection=%s chat=%s day=%s",
                        streak.business_connection_id,
                        streak.chat_id,
                        yesterday,
                    )

        await self.repository.cleanup_processed_messages()
