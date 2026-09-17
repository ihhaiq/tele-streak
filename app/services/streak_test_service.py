from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import secrets

from app.database.repository import Repository


@dataclass(frozen=True, slots=True)
class TestReviveState:
    token: str
    business_connection_id: str
    chat_id: int
    owner_user_id: int
    peer_user_id: int
    owner_approved: bool = False
    peer_approved: bool = False
    completed: bool = False
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TestReviveApproval:
    status: str
    state: TestReviveState | None = None
    ready: bool = False


class StreakTestService:
    """Ephemeral test state that never mutates a real streak or protection balance."""

    def __init__(self, repository: Repository):
        self.repository = repository
        self._requests: dict[str, TestReviveState] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _cleanup_locked(self) -> None:
        now = self._now()
        expired = [
            token
            for token, state in self._requests.items()
            if state.expires_at is not None and state.expires_at <= now
        ]
        for token in expired:
            self._requests.pop(token, None)

    async def create_revive_test(
        self,
        business_connection_id: str,
        chat_id: int,
        *,
        ttl_seconds: int = 900,
    ) -> TestReviveState | None:
        owner_user_id = await self.repository.get_owner_id(business_connection_id)
        streak = await self.repository.get_streak(business_connection_id, chat_id)
        if owner_user_id is None or streak is None or streak.peer_user_id is None:
            return None

        state = TestReviveState(
            token=secrets.token_urlsafe(8),
            business_connection_id=business_connection_id,
            chat_id=chat_id,
            owner_user_id=owner_user_id,
            peer_user_id=streak.peer_user_id,
            expires_at=self._now() + timedelta(seconds=ttl_seconds),
        )
        async with self._lock:
            self._cleanup_locked()
            for token, existing in list(self._requests.items()):
                if (
                    existing.business_connection_id == business_connection_id
                    and existing.chat_id == chat_id
                    and not existing.completed
                ):
                    self._requests.pop(token, None)
            self._requests[state.token] = state
        return state

    async def approve(self, token: str, user_id: int) -> TestReviveApproval:
        async with self._lock:
            self._cleanup_locked()
            state = self._requests.get(token)
            if state is None:
                return TestReviveApproval("expired")
            if state.completed:
                return TestReviveApproval("completed", state=state)

            if user_id == state.owner_user_id:
                already = state.owner_approved
                state = replace(state, owner_approved=True)
            elif user_id == state.peer_user_id:
                already = state.peer_approved
                state = replace(state, peer_approved=True)
            else:
                return TestReviveApproval("unauthorized", state=state)

            ready = state.owner_approved and state.peer_approved
            if ready:
                state = replace(state, completed=True)
            self._requests[token] = state
            return TestReviveApproval(
                "already" if already else "approved",
                state=state,
                ready=ready,
            )
