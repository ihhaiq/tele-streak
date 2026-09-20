from __future__ import annotations

import json
import secrets
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from app.adventures.rules import Activity, Profile, apply_activity, make_day

SCHEMA = """
CREATE TABLE IF NOT EXISTS adventure_profiles (
 business_connection_id TEXT NOT NULL, chat_id INTEGER NOT NULL,
 shared_xp INTEGER NOT NULL DEFAULT 0, shared_level INTEGER NOT NULL DEFAULT 1,
 state TEXT NOT NULL, story_claim_at REAL NOT NULL DEFAULT 0,
 PRIMARY KEY (business_connection_id, chat_id),
 FOREIGN KEY (business_connection_id) REFERENCES business_connections(business_connection_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS adventure_days (
 business_connection_id TEXT NOT NULL, chat_id INTEGER NOT NULL,
 day TEXT NOT NULL, state TEXT NOT NULL,
 PRIMARY KEY (business_connection_id, chat_id, day),
 FOREIGN KEY (business_connection_id) REFERENCES business_connections(business_connection_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS story_publish_requests (
 token TEXT PRIMARY KEY,
 business_connection_id TEXT NOT NULL,
 chat_id INTEGER NOT NULL,
 owner_user_id INTEGER NOT NULL,
 kind TEXT NOT NULL,
 media_path TEXT NOT NULL,
 thumbnail_path TEXT NOT NULL,
 days INTEGER NOT NULL,
 created_at REAL NOT NULL,
 expires_at REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'pending',
 published_story_id INTEGER,
 FOREIGN KEY (business_connection_id) REFERENCES business_connections(business_connection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_story_publish_requests_expiry
ON story_publish_requests(expires_at);
CREATE INDEX IF NOT EXISTS idx_story_publish_requests_chat
ON story_publish_requests(business_connection_id, chat_id, status);
"""
TABLES = ("adventure_profiles", "adventure_days", "story_publish_requests")


@dataclass(frozen=True, slots=True)
class StoryPublishRequest:
    token: str
    business_connection_id: str
    chat_id: int
    owner_user_id: int
    kind: str
    media_path: str
    thumbnail_path: str
    days: int
    created_at: float
    expires_at: float
    status: str
    published_story_id: int | None = None


def _story_request(row) -> StoryPublishRequest:
    return StoryPublishRequest(
        token=str(row["token"]),
        business_connection_id=str(row["business_connection_id"]),
        chat_id=int(row["chat_id"]),
        owner_user_id=int(row["owner_user_id"]),
        kind=str(row["kind"]),
        media_path=str(row["media_path"]),
        thumbnail_path=str(row["thumbnail_path"]),
        days=int(row["days"]),
        created_at=float(row["created_at"]),
        expires_at=float(row["expires_at"]),
        status=str(row["status"]),
        published_story_id=(
            int(row["published_story_id"])
            if row["published_story_id"] is not None
            else None
        ),
    )


async def load_profile(db, key, today: str) -> Profile:
    row = await (
        await db.execute(
            "SELECT state FROM adventure_profiles WHERE business_connection_id=? AND chat_id=?",
            key,
        )
    ).fetchone()
    return Profile(**json.loads(row["state"])) if row else Profile(tracked_since=today)


async def save_profile(db, key, profile: Profile) -> None:
    await db.execute(
        """INSERT INTO adventure_profiles
        (business_connection_id,chat_id,shared_xp,shared_level,state) VALUES (?,?,?,?,?)
        ON CONFLICT(business_connection_id,chat_id) DO UPDATE SET
        shared_xp=excluded.shared_xp, shared_level=excluded.shared_level,state=excluded.state""",
        (
            *key,
            profile.shared_xp,
            profile.shared_level,
            json.dumps(asdict(profile), ensure_ascii=False),
        ),
    )


async def load_day(db, key, day: str) -> dict | None:
    row = await (
        await db.execute(
            """SELECT state FROM adventure_days
        WHERE business_connection_id=? AND chat_id=? AND day=?""",
            (*key, day),
        )
    ).fetchone()
    return json.loads(row["state"]) if row else None


async def save_day(db, key, day, state):
    await db.execute(
        """INSERT INTO adventure_days VALUES (?,?,?,?)
        ON CONFLICT(business_connection_id,chat_id,day) DO UPDATE SET state=excluded.state""",
        (*key, day, json.dumps(state, ensure_ascii=False)),
    )


async def record_activity(
    db, key, activity: Activity, *, completed=False, restarted=False, freeze_count=3
) -> tuple[bool, bool]:
    """ينادى داخل نفس معاملة الستريك، قبل الحفظ النهائي."""
    day = activity.at.date().isoformat()
    latest = await (
        await db.execute(
            """SELECT MAX(day) FROM adventure_days
        WHERE business_connection_id=? AND chat_id=?""",
            key,
        )
    ).fetchone()
    # رجوع المنطقة الزمنية للخلف ما يفتح يوم قديم للمكافآت.
    if latest[0] and day < latest[0]:
        return False, False
    profile = await load_profile(db, key, day)
    yesterday = (activity.at.date() - timedelta(days=1)).isoformat()
    if profile.last_good_day and profile.last_good_day < yesterday:
        profile.combo = 0
        profile.last_good_day = None
    state = await load_day(db, key, day)
    if state is None:
        state = make_day(day, profile, activity.at.hour)
    celebrate = completed and restarted and not state["completed"]
    before_all = state["all_bonus"]
    notes, shield = apply_activity(
        profile,
        state,
        activity,
        completed=completed,
        restarted=restarted,
        freeze_count=freeze_count,
    )
    if shield:
        await db.execute(
            """UPDATE streaks SET freeze_count=MIN(3,freeze_count+1)
            WHERE business_connection_id=? AND chat_id=?""",
            key,
        )
    # إشعاران كحد أقصى: اكتمال اليوم، واكتمال كل المهام.
    notify = (
        bool(notes)
        and (completed or (state["all_bonus"] and not before_all))
        and state["notice_count"] < 2
    )
    if notes:
        previous = state.get("pending", [])
        state["pending"] = previous + notes
    if notify:
        state["notice_count"] += 1
        state["latest_notice"] = (
            "🔥 بدأ الستريك بينكم! Jake فرحان ببدايتكم 🎉\n" if celebrate else ""
        ) + "\n".join(state.pop("pending", []))
    await save_profile(db, key, profile)
    await save_day(db, key, day, state)
    return notify, celebrate


async def record_rescue(db, key, day: str, *, automatic: bool):
    profile = await load_profile(db, key, day)
    profile.combo = 0
    profile.last_good_day = None
    if automatic:
        profile.automatic_saves += 1
    else:
        # الإحياء يحتاج الطرفين، لذلك الإنجاز مشترك.
        for role in ("owner", "peer"):
            profile.stats[role]["saves"] += 1
    await save_profile(db, key, profile)


async def break_combo(db, key, day):
    profile = await load_profile(db, key, day)
    profile.combo = 0
    profile.last_good_day = None
    await save_profile(db, key, profile)


class AdventureRepository:
    def __init__(self, database):
        self.database = database

    async def snapshot(self, connection_id, chat_id, now: datetime):
        key = (connection_id, chat_id)
        today = now.date().isoformat()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            profile = await load_profile(db, key, today)
            yesterday = (now.date() - timedelta(days=1)).isoformat()
            if profile.last_good_day and profile.last_good_day < yesterday:
                profile.combo = 0
                profile.last_good_day = None
            state = await load_day(db, key, today)
            if state is None:
                state = make_day(today, profile, now.hour)
                await save_day(db, key, today, state)
            await save_profile(db, key, profile)
            await db.commit()
        return profile, state

    async def claim_story(self, connection_id, chat_id, timestamp: float) -> bool:
        async with self.database.connect() as db:
            result = await db.execute(
                """UPDATE adventure_profiles SET story_claim_at=?
                WHERE business_connection_id=? AND chat_id=? AND story_claim_at <= ?""",
                (timestamp, connection_id, chat_id, timestamp - 60),
            )
            return result.rowcount == 1

    async def release_story_claim(
        self, connection_id: str, chat_id: int, timestamp: float
    ) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """UPDATE adventure_profiles SET story_claim_at=0
                WHERE business_connection_id=? AND chat_id=? AND story_claim_at=?""",
                (connection_id, chat_id, timestamp),
            )
            await db.commit()


    async def create_story_publish_request(
        self,
        *,
        connection_id: str,
        chat_id: int,
        owner_user_id: int,
        kind: str,
        media_path: str,
        thumbnail_path: str,
        days: int,
        ttl_seconds: int = 900,
    ) -> tuple[StoryPublishRequest, list[str]]:
        now = time.time()
        expires_at = now + max(60, min(int(ttl_seconds), 3600))
        token = secrets.token_urlsafe(8)
        old_paths: list[str] = []
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            rows = await (
                await db.execute(
                    """SELECT media_path, thumbnail_path
                    FROM story_publish_requests
                    WHERE expires_at <= ?
                       OR (business_connection_id=? AND chat_id=? AND status='pending')""",
                    (now, connection_id, chat_id),
                )
            ).fetchall()
            for row in rows:
                old_paths.extend((str(row["media_path"]), str(row["thumbnail_path"])))
            await db.execute(
                """DELETE FROM story_publish_requests
                WHERE expires_at <= ?
                   OR (business_connection_id=? AND chat_id=? AND status='pending')""",
                (now, connection_id, chat_id),
            )
            await db.execute(
                """INSERT INTO story_publish_requests(
                    token, business_connection_id, chat_id, owner_user_id, kind,
                    media_path, thumbnail_path, days, created_at, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    token,
                    connection_id,
                    chat_id,
                    owner_user_id,
                    kind,
                    media_path,
                    thumbnail_path,
                    days,
                    now,
                    expires_at,
                ),
            )
            await db.commit()
        request = StoryPublishRequest(
            token=token,
            business_connection_id=connection_id,
            chat_id=chat_id,
            owner_user_id=owner_user_id,
            kind=kind,
            media_path=media_path,
            thumbnail_path=thumbnail_path,
            days=days,
            created_at=now,
            expires_at=expires_at,
            status="pending",
        )
        return request, old_paths

    async def get_story_publish_request(
        self, token: str, *, allow_expired: bool = False
    ) -> StoryPublishRequest | None:
        now = time.time()
        async with self.database.connect() as db:
            cursor = await db.execute(
                """SELECT * FROM story_publish_requests
                WHERE token=?"""
                + ("" if allow_expired else " AND expires_at>?"),
                (token,) if allow_expired else (token, now),
            )
            row = await cursor.fetchone()
            return _story_request(row) if row else None

    async def claim_story_publish(
        self, token: str, user_id: int
    ) -> tuple[str, StoryPublishRequest | None]:
        now = time.time()
        async with self.database.connect() as db:
            await db.execute("BEGIN IMMEDIATE")
            row = await (
                await db.execute(
                    """SELECT r.*, s.peer_user_id
                    FROM story_publish_requests AS r
                    LEFT JOIN streaks AS s
                      ON s.business_connection_id=r.business_connection_id
                     AND s.chat_id=r.chat_id
                    WHERE r.token=?""",
                    (token,),
                )
            ).fetchone()
            if row is None or float(row["expires_at"]) <= now:
                await db.rollback()
                return "expired", None
            request = _story_request(row)
            peer_id = int(row["peer_user_id"]) if row["peer_user_id"] is not None else request.chat_id
            if user_id not in {request.owner_user_id, peer_id}:
                await db.rollback()
                return "unauthorized", request
            if request.status == "published":
                await db.rollback()
                return "published", request
            if request.status == "publishing":
                await db.rollback()
                return "publishing", request
            updated = await db.execute(
                """UPDATE story_publish_requests
                SET status='publishing'
                WHERE token=? AND status='pending' AND expires_at>?""",
                (token, now),
            )
            if updated.rowcount != 1:
                await db.rollback()
                return "publishing", request
            await db.commit()
            return "ready", request

    async def complete_story_publish(self, token: str, story_id: int) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """UPDATE story_publish_requests
                SET status='published', published_story_id=?
                WHERE token=?""",
                (story_id, token),
            )
            await db.commit()

    async def release_story_publish(self, token: str) -> None:
        async with self.database.connect() as db:
            await db.execute(
                """UPDATE story_publish_requests
                SET status='pending'
                WHERE token=? AND status='publishing' AND expires_at>?""",
                (token, time.time()),
            )
            await db.commit()


    async def delete_story_publish_request(
        self, token: str
    ) -> list[str]:
        async with self.database.connect() as db:
            row = await (
                await db.execute(
                    """SELECT media_path, thumbnail_path
                    FROM story_publish_requests WHERE token=?""",
                    (token,),
                )
            ).fetchone()
            await db.execute(
                "DELETE FROM story_publish_requests WHERE token=?",
                (token,),
            )
            await db.commit()
        if row is None:
            return []
        return [str(row["media_path"]), str(row["thumbnail_path"])]
