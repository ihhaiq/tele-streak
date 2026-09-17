from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets

from .engine import Database


@dataclass(frozen=True, slots=True)
class GuestAction:
    token: str
    action: str
    business_connection_id: str
    chat_id: int


class GuestActionRepository:
    """Short-lived context for callback buttons attached to guest messages."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def create(
        self,
        *,
        action: str,
        business_connection_id: str,
        chat_id: int,
        ttl_seconds: int = 86_400,
    ) -> str:
        now = self._now()
        token = secrets.token_urlsafe(8)
        async with self.database.connect() as db:
            await db.execute(
                "DELETE FROM guest_streak_actions WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            await db.execute(
                """
                INSERT INTO guest_streak_actions(
                    token, action, business_connection_id, chat_id,
                    created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    action,
                    business_connection_id,
                    chat_id,
                    now.isoformat(),
                    (now + timedelta(seconds=ttl_seconds)).isoformat(),
                ),
            )
            await db.commit()
        return token

    async def consume(self, token: str, *, action: str) -> GuestAction | None:
        now = self._now().isoformat()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "DELETE FROM guest_streak_actions WHERE expires_at <= ?",
                (now,),
            )
            cursor = await db.execute(
                """
                SELECT token, action, business_connection_id, chat_id
                FROM guest_streak_actions
                WHERE token=? AND action=? AND expires_at>?
                """,
                (token, action, now),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            await db.execute(
                "DELETE FROM guest_streak_actions WHERE token=?",
                (token,),
            )
            await db.commit()
            return GuestAction(
                token=str(row["token"]),
                action=str(row["action"]),
                business_connection_id=str(row["business_connection_id"]),
                chat_id=int(row["chat_id"]),
            )
