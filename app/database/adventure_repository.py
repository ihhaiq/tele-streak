from __future__ import annotations

import json
from dataclasses import asdict
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
"""
TABLES = ("adventure_profiles", "adventure_days")


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
