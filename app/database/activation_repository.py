from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets

from app.database.engine import Database


@dataclass(frozen=True, slots=True)
class StreakStartRequest:
    token: str
    business_connection_id: str
    chat_id: int
    owner_user_id: int
    owner_chat_id: int
    peer_user_id: int
    source_message_id: int


class StreakActivationRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    async def get_owner_target(self, connection_id: str) -> tuple[int, int] | None:
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT owner_user_id, user_chat_id
                FROM business_connections
                WHERE business_connection_id=? AND is_enabled=1
                """,
                (connection_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            owner_id = int(row["owner_user_id"])
            owner_chat_id = (
                int(row["user_chat_id"])
                if row["user_chat_id"] is not None
                else owner_id
            )
            return owner_id, owner_chat_id

    async def create_request(
        self,
        *,
        connection_id: str,
        chat_id: int,
        peer_user_id: int,
        source_message_id: int,
        ttl_hours: int = 24,
    ) -> str | None:
        now_dt = self._now()
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(hours=ttl_hours)).isoformat()
        token = secrets.token_urlsafe(8)

        async with self.database.connect() as db:
            await db.execute(
                "DELETE FROM streak_start_requests WHERE expires_at <= ?",
                (now,),
            )
            cursor = await db.execute(
                """
                SELECT 1
                FROM streak_start_requests
                WHERE business_connection_id=? AND chat_id=?
                LIMIT 1
                """,
                (connection_id, chat_id),
            )
            if await cursor.fetchone() is not None:
                await db.commit()
                return None

            await db.execute(
                """
                INSERT INTO streak_start_requests(
                    token, business_connection_id, chat_id,
                    peer_user_id, source_message_id, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    connection_id,
                    chat_id,
                    peer_user_id,
                    source_message_id,
                    now,
                    expires_at,
                ),
            )
            await db.commit()
        return token

    async def get_request(self, token: str) -> StreakStartRequest | None:
        now = self._now().isoformat()
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT r.token, r.business_connection_id, r.chat_id,
                       r.peer_user_id, r.source_message_id,
                       b.owner_user_id, b.user_chat_id
                FROM streak_start_requests AS r
                JOIN business_connections AS b
                  ON b.business_connection_id=r.business_connection_id
                WHERE r.token=? AND r.expires_at>? AND b.is_enabled=1
                """,
                (token, now),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            owner_id = int(row["owner_user_id"])
            return StreakStartRequest(
                token=str(row["token"]),
                business_connection_id=str(row["business_connection_id"]),
                chat_id=int(row["chat_id"]),
                owner_user_id=owner_id,
                owner_chat_id=(
                    int(row["user_chat_id"])
                    if row["user_chat_id"] is not None
                    else owner_id
                ),
                peer_user_id=int(row["peer_user_id"]),
                source_message_id=int(row["source_message_id"]),
            )

    async def finish_request(self, token: str) -> None:
        async with self.database.connect() as db:
            await db.execute(
                "DELETE FROM streak_start_requests WHERE token=?",
                (token,),
            )
            await db.commit()

    async def clear_chat(self, connection_id: str, chat_id: int) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """
                DELETE FROM streak_start_requests
                WHERE business_connection_id=? AND chat_id=?
                """,
                (connection_id, chat_id),
            )
            await db.commit()
