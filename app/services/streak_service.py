from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram.types import Message

from app.adventures.rules import Activity
from app.database.activation_repository import StreakActivationRepository
from app.database.repository import Repository
from app.services.message_filter import matches_streak_mode
from app.stickers.poses import PoseCatalog

logger = logging.getLogger(__name__)
OWNER_CACHE_SIZE = 512
LOCK_CACHE_SIZE = 1024


@dataclass(slots=True)
class Completion:
    completed: bool
    days: int = 0
    pose: str | None = None
    duplicate: bool = False
    adventure_notice: bool = False
    celebrate: bool = False


@dataclass(slots=True)
class StreakStatus:
    current: int
    longest: int
    completed_days: int
    break_count: int
    freeze_count: int
    last_completed_day: str | None


class StreakService:
    def __init__(
        self,
        repository: Repository,
        activations: StreakActivationRepository,
        timezone_name: str,
        poses: PoseCatalog,
    ):
        self.repository = repository
        self.activations = activations
        self.tz = ZoneInfo(timezone_name)
        self.poses = poses
        self._locks: defaultdict[tuple[str, int], asyncio.Lock] = defaultdict(asyncio.Lock)
        # connection_id -> owner id, so a hot chat does not query SQLite twice
        # per message. Bounded because a bot serves a finite set of accounts.
        self._owner_cache: OrderedDict[str, int] = OrderedDict()

    def _remember_owner(self, connection_id: str, owner_id: int) -> None:
        self._owner_cache[connection_id] = owner_id
        self._owner_cache.move_to_end(connection_id)
        while len(self._owner_cache) > OWNER_CACHE_SIZE:
            self._owner_cache.popitem(last=False)

    def forget_owner(self, connection_id: str) -> None:
        self._owner_cache.pop(connection_id, None)

    def _release_lock(self, key: tuple[str, int]) -> None:
        lock = self._locks.get(key)
        if lock is not None and not lock.locked() and len(self._locks) > LOCK_CACHE_SIZE:
            self._locks.pop(key, None)

    async def _days(self, connection_id: str) -> tuple[str, str]:
        timezone_name = await self.repository.get_connection_timezone(connection_id)
        timezone = ZoneInfo(timezone_name) if timezone_name else self.tz
        today_date = datetime.now(timezone).date()
        return today_date.isoformat(), (today_date - timedelta(days=1)).isoformat()

    async def _ensure_owner(self, message: Message) -> int | None:
        connection_id = message.business_connection_id
        if not connection_id:
            return None
        cached = self._owner_cache.get(connection_id)
        if cached is not None:
            self._owner_cache.move_to_end(connection_id)
            return cached
        owner_id = await self.repository.get_owner_id(connection_id)
        if owner_id is not None:
            self._remember_owner(connection_id, owner_id)
            return owner_id
        try:
            connection = await message.bot.get_business_connection(connection_id)
            await self.repository.upsert_connection(
                connection_id=connection.id,
                owner_user_id=connection.user.id,
                user_chat_id=connection.user_chat_id,
                is_enabled=connection.is_enabled,
            )
            if connection.is_enabled:
                self._remember_owner(connection.id, connection.user.id)
            logger.info(
                "BUSINESS_CONNECTION_RECOVERED connection=%s owner=%s",
                connection.id,
                connection.user.id,
            )
            return connection.user.id if connection.is_enabled else None
        except Exception:
            logger.exception(
                "BUSINESS_CONNECTION_RECOVERY_FAILED connection=%s",
                connection_id,
            )
            return None

    async def get_owner_id(self, message: Message) -> int | None:
        return await self._ensure_owner(message)

    async def get_status(self, message: Message) -> StreakStatus | None:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return None
        if await self._ensure_owner(message) is None:
            return None
        record = await self.repository.get_streak(connection_id, message.chat.id)
        if record is None:
            return StreakStatus(0, 0, 0, 0, 0, None)
        return StreakStatus(
            current=record.current_streak,
            longest=record.longest_streak,
            completed_days=record.completed_days,
            break_count=record.break_count,
            freeze_count=record.freeze_count,
            last_completed_day=record.last_completed_day,
        )

    async def register_message(self, message: Message) -> Completion:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return Completion(False)
        key = (connection_id, message.chat.id)
        async with self._locks[key]:
            owner_id = await self._ensure_owner(message)
            active = await self.activations.is_active(connection_id, message.chat.id)
            if owner_id is None or not active:
                completion = Completion(False)
            else:
                record = await self.repository.get_streak(connection_id, message.chat.id)
                if record is not None and not record.is_enabled:
                    completion = Completion(False)
                else:
                    sender_id = message.from_user.id
                    role = "owner" if sender_id == owner_id else "peer"
                    peer_id = None if role == "owner" else sender_id
                    zone = await self.repository.get_connection_timezone(connection_id)
                    now = datetime.now(ZoneInfo(zone)) if zone else datetime.now(self.tz)
                    today = now.date().isoformat()
                    yesterday = (now.date() - timedelta(days=1)).isoformat()
                    qualifies = record is None or matches_streak_mode(message, record.streak_mode)
                    kind = next((kind for kind in ('photo', 'video', 'voice')
                                 if getattr(message, kind, None)), '')
                    activity = Activity(
                        at=now, role=role, kind=kind, qualifies=qualifies,
                        words=len((getattr(message, 'text', None) or getattr(message, 'caption', None) or '').split()),
                        name=getattr(message.from_user, 'full_name', ''),
                    )
                    sent_at = getattr(message, 'date', None)
                    if isinstance(sent_at, datetime) and sent_at.astimezone(now.tzinfo).date() != now.date():
                        # تحديث قديم ما ياخذ مكافآت يوم جديد.
                        activity = None
                    result = await self.repository.register_activity(
                        connection_id=connection_id,
                        chat_id=message.chat.id,
                        message_id=message.message_id,
                        peer_user_id=peer_id,
                        role=role,
                        today=today,
                        yesterday=yesterday,
                        choose_pose=lambda days, last_pose: self.poses.choose(days, last_pose).id,
                        adventure=activity, qualifies=qualifies,
                    )
                    completion = Completion(
                        completed=result.completed,
                        days=result.days,
                        pose=result.pose_id,
                        duplicate=result.duplicate,
                        adventure_notice=result.adventure_notice,
                        celebrate=result.celebrate,
                    )
        self._release_lock(key)
        return completion

    async def start_by_owner(self, message: Message) -> Completion:
        connection_id = message.business_connection_id
        if not connection_id or message.from_user is None:
            return Completion(False)
        key = (connection_id, message.chat.id)
        async with self._locks[key]:
            owner_id = await self._ensure_owner(message)
            if owner_id is None or message.from_user.id != owner_id:
                completion = Completion(False)
            else:
                await self.activations.activate(connection_id, message.chat.id)
                today, yesterday = await self._days(connection_id)
                result = await self.repository.register_activity(
                    connection_id=connection_id,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    peer_user_id=None,
                    role="owner",
                    today=today,
                    yesterday=yesterday,
                    choose_pose=lambda days, last_pose: self.poses.choose(days, last_pose).id,
                    adventure=Activity(
                        at=datetime.now(ZoneInfo(await self.repository.get_connection_timezone(connection_id) or self.tz.key)),
                        role="owner",
                    ),
                )
                completion = Completion(
                    completed=result.completed,
                    days=result.days,
                    pose=result.pose_id,
                    duplicate=result.duplicate,
                )
        self._release_lock(key)
        return completion

    async def start_from_peer_request(
        self,
        *,
        connection_id: str,
        chat_id: int,
        peer_user_id: int,
        source_message_id: int,
    ) -> Completion:
        key = (connection_id, chat_id)
        async with self._locks[key]:
            if await self.activations.is_active(connection_id, chat_id):
                record = await self.repository.get_streak(connection_id, chat_id)
                completion = Completion(
                    False,
                    days=record.current_streak if record is not None else 0,
                )
            else:
                await self.activations.activate(connection_id, chat_id)
                today, yesterday = await self._days(connection_id)
                result = await self.repository.register_activity(
                    connection_id=connection_id,
                    chat_id=chat_id,
                    message_id=source_message_id,
                    peer_user_id=peer_user_id,
                    role="peer",
                    today=today,
                    yesterday=yesterday,
                    choose_pose=lambda days, last_pose: self.poses.choose(days, last_pose).id,
                    adventure=Activity(
                        at=datetime.now(ZoneInfo(await self.repository.get_connection_timezone(connection_id) or self.tz.key)),
                        role="peer",
                    ),
                )
                completion = Completion(
                    completed=result.completed,
                    days=result.days,
                    pose=result.pose_id,
                    duplicate=result.duplicate,
                )
        self._release_lock(key)
        return completion
