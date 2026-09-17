from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets

from .engine import Database


@dataclass(frozen=True, slots=True)
class ReviveApprovalState:
    token: str
    business_connection_id: str
    chat_id: int
    owner_user_id: int
    peer_user_id: int
    owner_approved: bool
    peer_approved: bool
    completed: bool = False


@dataclass(frozen=True, slots=True)
class ReviveApprovalResult:
    status: str
    state: ReviveApprovalState | None = None
    ready: bool = False


class ReviveRequestRepository:
    """Coordinates two-party approval before a broken streak can be revived."""

    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _state(row) -> ReviveApprovalState:
        return ReviveApprovalState(
            token=str(row["token"]),
            business_connection_id=str(row["business_connection_id"]),
            chat_id=int(row["chat_id"]),
            owner_user_id=int(row["owner_user_id"]),
            peer_user_id=int(row["peer_user_id"]),
            owner_approved=bool(row["owner_approved"]),
            peer_approved=bool(row["peer_approved"]),
            completed=row["completed_at"] is not None,
        )

    async def create_or_get(
        self,
        business_connection_id: str,
        chat_id: int,
        *,
        ttl_seconds: int = 900,
    ) -> ReviveApprovalState | None:
        now_dt = self._now()
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=ttl_seconds)).isoformat()

        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "DELETE FROM streak_revive_requests WHERE expires_at <= ?",
                (now,),
            )
            cursor = await db.execute(
                """
                SELECT b.owner_user_id, s.peer_user_id
                FROM streaks AS s
                JOIN business_connections AS b
                  ON b.business_connection_id=s.business_connection_id
                WHERE s.business_connection_id=? AND s.chat_id=?
                  AND b.is_enabled=1 AND s.is_enabled=1
                  AND s.current_streak=0 AND s.revivable_streak>0
                  AND s.peer_user_id IS NOT NULL
                """,
                (business_connection_id, chat_id),
            )
            participants = await cursor.fetchone()
            if participants is None:
                await db.rollback()
                return None

            cursor = await db.execute(
                """
                SELECT * FROM streak_revive_requests
                WHERE business_connection_id=? AND chat_id=?
                  AND completed_at IS NULL AND expires_at>?
                LIMIT 1
                """,
                (business_connection_id, chat_id, now),
            )
            existing = await cursor.fetchone()
            if existing is not None:
                await db.commit()
                return self._state(existing)

            await db.execute(
                "DELETE FROM streak_revive_requests WHERE business_connection_id=? AND chat_id=?",
                (business_connection_id, chat_id),
            )
            token = secrets.token_urlsafe(8)
            await db.execute(
                """
                INSERT INTO streak_revive_requests(
                    token, business_connection_id, chat_id,
                    owner_user_id, peer_user_id,
                    owner_approved, peer_approved,
                    created_at, expires_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, NULL)
                """,
                (
                    token,
                    business_connection_id,
                    chat_id,
                    int(participants["owner_user_id"]),
                    int(participants["peer_user_id"]),
                    now,
                    expires_at,
                ),
            )
            cursor = await db.execute(
                "SELECT * FROM streak_revive_requests WHERE token=?",
                (token,),
            )
            row = await cursor.fetchone()
            await db.commit()
            assert row is not None
            return self._state(row)

    async def get(self, token: str) -> ReviveApprovalState | None:
        now = self._now().isoformat()
        async with self.database.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM streak_revive_requests
                WHERE token=? AND expires_at>?
                """,
                (token, now),
            )
            row = await cursor.fetchone()
            return self._state(row) if row is not None else None

    async def approve(self, token: str, user_id: int) -> ReviveApprovalResult:
        now = self._now().isoformat()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "DELETE FROM streak_revive_requests WHERE expires_at <= ?",
                (now,),
            )
            cursor = await db.execute(
                "SELECT * FROM streak_revive_requests WHERE token=?",
                (token,),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return ReviveApprovalResult("expired")

            state = self._state(row)
            if state.completed:
                await db.commit()
                return ReviveApprovalResult("completed", state=state)

            if user_id == state.owner_user_id:
                column = "owner_approved"
                already = state.owner_approved
            elif user_id == state.peer_user_id:
                column = "peer_approved"
                already = state.peer_approved
            else:
                await db.rollback()
                return ReviveApprovalResult("unauthorized", state=state)

            if not already:
                await db.execute(
                    f"UPDATE streak_revive_requests SET {column}=1 WHERE token=?",
                    (token,),
                )

            cursor = await db.execute(
                "SELECT * FROM streak_revive_requests WHERE token=?",
                (token,),
            )
            row = await cursor.fetchone()
            assert row is not None
            state = self._state(row)
            ready = state.owner_approved and state.peer_approved
            if ready:
                await db.execute(
                    "UPDATE streak_revive_requests SET completed_at=? WHERE token=? AND completed_at IS NULL",
                    (now, token),
                )
                cursor = await db.execute(
                    "SELECT * FROM streak_revive_requests WHERE token=?",
                    (token,),
                )
                row = await cursor.fetchone()
                assert row is not None
                state = self._state(row)

            await db.commit()
            return ReviveApprovalResult(
                "already" if already else "approved",
                state=state,
                ready=ready,
            )
