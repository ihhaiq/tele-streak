import asyncio
import random
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.adventures.rules import (
    Activity,
    Profile,
    level_progress,
    make_day,
)
from app.adventures.tasks import (
    TASK_CATALOG,
    active_task_specs,
    choose_tasks,
    task_slot,
)
from app.adventures.views import navigation, page_text, rich_page
from app.database import adventure_repository as module
from app.database.activation_repository import StreakActivationRepository
from app.database.adventure_repository import (
    AdventureRepository,
)
from app.database.engine import SCHEMA, Database
from app.database.repository import Repository


def at(day=20, hour=12, minute=0, second=0):
    return datetime(2026, 9, day, hour, minute, second, tzinfo=ZoneInfo("Asia/Baghdad"))


def state(tasks=("owner_texts_1", "peer_photo_1"), event=""):
    result = make_day("2026-09-20", Profile(), 12, random.Random(3))
    result.update(tasks=list(tasks), event=event, secret_roll=False)
    return result


async def setup(path):
    db = Database(path)
    await db.init()
    repo = Repository(db)
    await repo.upsert_connection("bc", 10, 10, True)
    await StreakActivationRepository(db).activate("bc", 20)
    return db, repo, AdventureRepository(db)


async def send(
    repo,
    mid,
    role="owner",
    when=None,
    kind="",
    words=0,
    qualifies=True,
    connection="bc",
):
    now = when or at()
    return await repo.register_activity(
        connection_id=connection,
        chat_id=20,
        message_id=mid,
        peer_user_id=30 if role == "peer" else None,
        role=role,
        today=now.date().isoformat(),
        yesterday=(now.date() - timedelta(days=1)).isoformat(),
        choose_pose=lambda *_: "pose",
        qualifies=qualifies,
        adventure=Activity(
            now, role, kind, words, qualifies, "حسين" if role == "owner" else "صديق"
        ),
    )


@pytest.mark.parametrize(
    "xp,expected",
    [
        (0, (1, 0, 100)),
        (99, (1, 99, 100)),
        (100, (2, 0, 200)),
        (299, (2, 199, 200)),
        (300, (3, 0, 300)),
        (600, (4, 0, 400)),
    ],
)
def test_level_boundaries(xp, expected):
    assert level_progress(xp) == expected


def test_duplicate_concurrent_updates_restart_and_reconnect(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "make_day", lambda *_: state())

    async def run():
        path = tmp_path / "test.db"
        db, repo, data = await setup(path)
        try:
            await send(repo, 1, words=3)
            results = await asyncio.gather(
                *[send(repo, 2, "peer", at(minute=1), kind="photo") for _ in range(8)]
            )
            assert sum(r.completed for r in results) == 1
            assert sum(r.celebrate for r in results) == 1
            assert sum(r.duplicate for r in results) == 7
            profile, daily = await data.snapshot("bc", 20, at())
            assert profile.shared_xp == 73  # 11 + 17 + all 20 + day 20 + combo 5
            assert profile.stats["owner"]["days"] == profile.stats["peer"]["days"] == 1
            assert profile.stats["owner"]["started"] == 1
            assert len(daily["done"]) == 2
            await db.close()
            db = Database(path)
            await db.init()
            repo = Repository(db)
            data = AdventureRepository(db)
            assert (await data.snapshot("bc", 20, at()))[0] == profile
            await repo.upsert_connection("bc", 10, 10, False)
            await repo.upsert_connection("reconnected", 10, 10, True)
            moved, moved_day = await data.snapshot("reconnected", 20, at())
            assert moved == profile and moved_day == daily
            assert (await send(repo, 2, "peer", connection="reconnected")).duplicate
            assert (await repo.get_streak("reconnected", 20)).current_streak == 1
        finally:
            await db.close()

    asyncio.run(run())


def test_media_mission_does_not_complete_text_streak(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "make_day", lambda *_: state())

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1, words=3)
            result = await send(repo, 2, "peer", kind="photo", qualifies=False)
            assert not result.completed
            record = await repo.get_streak("bc", 20)
            assert (
                record.owner_sent_day == "2026-09-20" and record.peer_sent_day is None
            )
            profile, daily = await data.snapshot("bc", 20, at())
            assert set(daily["done"]) == {"owner_texts_1", "peer_photo_1"}
            assert profile.shared_xp == 48
            assert profile.stats["peer"]["days"] == 0
            assert (await send(repo, 3, "peer", at(minute=3))).completed
        finally:
            await db.close()

    asyncio.run(run())


def test_atomic_rollback_and_retry(tmp_path, monkeypatch):
    original = module.record_activity

    async def fail(*args, **kwargs):
        raise RuntimeError("injected failure")

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1)
            monkeypatch.setattr(module, "record_activity", fail)
            with pytest.raises(RuntimeError):
                await send(repo, 2, "peer")
            assert (await repo.get_streak("bc", 20)).current_streak == 0
            monkeypatch.setattr(module, "record_activity", original)
            assert (await send(repo, 2, "peer")).completed
        finally:
            await db.close()

    asyncio.run(run())


def test_combo_breaks_with_delay_gap_freeze_revive_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "make_day", lambda *_: state(("owner_photo_1", "peer_video_1")))

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            for day in (20, 21):
                await send(repo, day * 2, when=at(day))
                await send(repo, day * 2 + 1, "peer", at(day, minute=2))
            assert (await data.snapshot("bc", 20, at(21)))[0].combo == 2
            await send(repo, 44, when=at(22))
            await send(repo, 45, "peer", at(22, hour=23))
            profile, _ = await data.snapshot("bc", 20, at(22))
            assert profile.combo == 0 and profile.stats["peer"]["late"] == 1
            await repo.toggle_chat_setting(10, 20, "auto_freeze")
            assert (
                await repo.process_missed_day(
                    connection_id="bc",
                    chat_id=20,
                    today="2026-09-24",
                    missed_day="2026-09-23",
                    day_before_missed="2026-09-22",
                )
                == "frozen"
            )
            profile, _ = await data.snapshot("bc", 20, at(24))
            assert profile.combo == 0 and profile.automatic_saves == 1
            await repo.toggle_chat_setting(10, 20, "auto_freeze")
            assert (
                await repo.process_missed_day(
                    connection_id="bc",
                    chat_id=20,
                    today="2026-09-25",
                    missed_day="2026-09-24",
                    day_before_missed="2026-09-23",
                )
                == "broken"
            )
            before = profile.shared_xp
            assert (await repo.revive_streak("bc", 20)).status == "revived"
            assert (await repo.revive_streak("bc", 20)).status == "unavailable"
            profile, _ = await data.snapshot("bc", 20, at(25))
            assert profile.shared_xp == before
            assert (
                profile.stats["owner"]["saves"] == profile.stats["peer"]["saves"] == 1
            )
            await repo.reset_streak(10, 20)
            assert (await data.snapshot("bc", 20, at(25)))[0].shared_xp == before
        finally:
            await db.close()

    asyncio.run(run())


@pytest.mark.parametrize("event", ["double", "shield", "combo", "rare", "fast", "calm"])
def test_events_reward_once_and_protection_is_capped(tmp_path, monkeypatch, event):
    monkeypatch.setattr(module, "make_day", lambda *_: state(("owner_texts_1", "peer_photo_1"), event))

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1, words=3)
            await send(repo, 2, "peer", at(minute=1), kind="photo")
            before = (await data.snapshot("bc", 20, at()))[0]
            await send(repo, 3, "peer", at(minute=2), kind="photo", words=3)
            after = (await data.snapshot("bc", 20, at()))[0]
            assert after.shared_xp == before.shared_xp
            assert (await repo.get_streak("bc", 20)).freeze_count == 3
            if event == "double":
                assert before.shared_xp == 146
            if event == "shield":
                assert before.shared_xp == 93
        finally:
            await db.close()

    asyncio.run(run())


def test_free_shield_is_granted_at_completion_not_page_open(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "make_day", lambda *_: state(event="shield"))

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1)
            async with db.connect() as conn:
                await conn.execute("UPDATE streaks SET freeze_count=1")
            await data.snapshot("bc", 20, at())
            assert (await repo.get_streak("bc", 20)).freeze_count == 1
            await send(repo, 2, "peer", at(minute=1))
            assert (await repo.get_streak("bc", 20)).freeze_count == 2
            await send(repo, 3, "peer")
            assert (await repo.get_streak("bc", 20)).freeze_count == 2
        finally:
            await db.close()

    asyncio.run(run())


def test_daily_rollover_does_not_reroll_or_reveal_secrets(tmp_path, monkeypatch):
    def day_state(day, *_):
        result = state()
        result["task_slot"] = f"{day}:2"
        return result

    monkeypatch.setattr(module, "make_day", day_state)

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1, words=3)
            p, d = await data.snapshot("bc", 20, at())
            assert "توأم اللحظة" not in page_text(p, d, "badges")
            await send(repo, 2, "peer", at(second=20))
            p, d = await data.snapshot("bc", 20, at())
            assert "توأم اللحظة" in page_text(p, d, "badges")
            _, fresh = await data.snapshot("bc", 20, at(21))
            assert fresh["done"] == []
            assert (await data.snapshot("bc", 20, at(21)))[1] == fresh
            xp = (await data.snapshot("bc", 20, at(21)))[0].shared_xp
            await send(repo, 3, "peer", at(), kind="photo")
            assert (await data.snapshot("bc", 20, at(21)))[0].shared_xp == xp
        finally:
            await db.close()

    asyncio.run(run())


def test_mode_switch_cannot_farm_stats_and_reset_cannot_farm_xp(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "make_day", lambda *_: state())

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1, words=3)
            await repo.set_streak_mode(10, "bc", 20, "voice", "2026-09-20")
            await send(repo, 2, kind="voice")
            p, _ = await data.snapshot("bc", 20, at())
            assert p.stats["owner"]["days"] == 1 and p.stats["owner"]["started"] == 1
            await send(repo, 3, "peer", at(minute=1), kind="voice")
            before, _ = await data.snapshot("bc", 20, at())
            await repo.reset_streak(10, 20)
            await send(repo, 4, kind="voice")
            replay = await send(repo, 5, "peer", kind="voice")
            after, _ = await data.snapshot("bc", 20, at())
            assert after.shared_xp == before.shared_xp
            assert not replay.celebrate
        finally:
            await db.close()

    asyncio.run(run())


def test_migration_preserves_existing_streak_and_is_repeatable(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO business_connections VALUES ('old',10,10,1,'UTC','2026-09-01')"
        )
        conn.execute("""INSERT INTO streaks(business_connection_id,chat_id,current_streak,longest_streak,
                     completed_days,last_completed_day,created_at,updated_at) VALUES ('old',20,8,12,40,'2026-09-19','2026-09-01','2026-09-19')""")

    async def run():
        db = Database(path)
        try:
            await db.init()
            await db.init()
            record = await Repository(db).get_streak("old", 20)
            assert (
                record.current_streak,
                record.longest_streak,
                record.completed_days,
            ) == (8, 12, 40)
            p, _ = await AdventureRepository(db).snapshot("old", 20, at())
            assert p.shared_xp == 0 and p.stats["owner"]["days"] == 0
        finally:
            await db.close()

    asyncio.run(run())


def test_cooldown_and_callback_size(tmp_path):
    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await data.snapshot("bc", 20, at())
            assert await data.claim_story("bc", 20, 1000)
            assert not await data.claim_story("bc", 20, 1020)
            assert await data.claim_story("bc", 20, 1060)
        finally:
            await db.close()

    asyncio.run(run())
    assert all(
        len(b.callback_data.encode()) <= 64
        for r in navigation(123456789012, 987654321098).inline_keyboard
        for b in r
    )


def test_random_event_frequency_cooldown_and_tasks_bounds():
    profile = Profile()
    rng = random.Random(52)
    events = 0
    for day in range(3650):
        now = at() + timedelta(days=day)
        previous = profile.last_event_day
        daily = make_day(now.date().isoformat(), profile, 23, rng)
        assert len(daily["tasks"]) == 6
        specs = active_task_specs(daily)
        assert len({spec.xp for spec in specs}) == 6
        if daily["event"]:
            events += 1
            if previous:
                assert (now.date() - datetime.fromisoformat(previous).date()).days >= 3
    assert 350 < events < 650


def test_rich_names_are_escaped():
    p = Profile()
    p.stats["owner"]["name"] = "<tg-button>bad</tg-button>"
    rich = rich_page(p, state(), "compare", 10, 20)
    assert "&lt;tg-button&gt;" in rich.html
    assert "<tg-button>bad" not in rich.html


def test_manual_streak_increment_does_not_grant_xp(tmp_path):
    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            await send(repo, 1)
            await send(repo, 2, "peer")
            before, _ = await data.snapshot("bc", 20, at())
            await repo.add_streak_days(connection_id="bc", chat_id=20, days=50)
            after, _ = await data.snapshot("bc", 20, at())
            assert after == before
            assert (await repo.get_streak("bc", 20)).current_streak == 51
        finally:
            await db.close()

    asyncio.run(run())


def test_rare_event_secret_unlock_is_once():
    from app.adventures.rules import apply_activity

    profile = Profile()
    daily = state(("owner_photo_1", "peer_photo_1"), "rare")
    daily["secret_roll"] = True
    apply_activity(
        profile,
        daily,
        Activity(at(), "owner", "photo", 0),
        completed=False,
        restarted=False,
        freeze_count=3,
    )
    assert "secret_lucky" not in profile.badges
    apply_activity(
        profile,
        daily,
        Activity(at(minute=1), "peer", "photo"),
        completed=True,
        restarted=True,
        freeze_count=3,
    )
    assert "secret_lucky" in profile.badges
    xp = profile.shared_xp
    apply_activity(
        profile,
        daily,
        Activity(at(minute=2), "peer", "photo"),
        completed=True,
        restarted=False,
        freeze_count=3,
    )
    assert profile.shared_xp == xp


def test_single_task_completion_emits_notice_and_persists_done_state(tmp_path, monkeypatch):
    monkeypatch.setattr(
        module,
        "make_day",
        lambda *_: state(("owner_texts_1", "peer_photo_1")),
    )

    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            result = await send(repo, 1, words=3)
            assert not result.completed
            assert result.adventure_notice

            profile, daily = await data.snapshot("bc", 20, at())
            assert daily["done"] == ["owner_texts_1"]
            assert "مهمة خلصت:" in daily["latest_notice"]
            assert "حسين يرسل 1 رسالة نصية" in daily["latest_notice"]
            assert profile.shared_xp > 0

            second = await send(repo, 2, words=3)
            assert not second.adventure_notice
            _, same = await data.snapshot("bc", 20, at())
            assert same["done"] == ["owner_texts_1"]
        finally:
            await db.close()

    asyncio.run(run())


def test_completed_task_is_checked_and_struck_in_fresh_views():
    profile = Profile()
    profile.stats["owner"]["name"] = "حسين"
    profile.stats["peer"]["name"] = "أحمد"
    daily = state(("owner_texts_1", "peer_photo_1"))
    daily["done"] = ["owner_texts_1"]

    text = page_text(profile, daily, "tasks")
    assert "✅ حسين يرسل 1 رسالة نصية" in text
    assert "○ أحمد يرسل 1 صورة" in text

    rich = rich_page(profile, daily, "tasks", 10, 20)
    assert "✅" in rich.html
    assert "<s>حسين يرسل 1 رسالة نصية</s>" in rich.html
    assert "<s>أحمد يرسل 1 صورة</s>" not in rich.html


def test_task_catalog_has_more_than_300_real_tasks():
    assert len(TASK_CATALOG) > 300
    assert len(TASK_CATALOG) == len(set(TASK_CATALOG))
    assert all(spec.label and spec.xp > 0 for spec in TASK_CATALOG.values())


def test_each_six_hour_batch_has_six_unique_xp_values():
    for seed in range(50):
        selected = choose_tasks(random.Random(seed))
        specs = [TASK_CATALOG[key] for key in selected]
        assert len(selected) == 6
        assert len(set(selected)) == 6
        assert len({spec.xp for spec in specs}) == 6


def test_task_slot_changes_exactly_every_six_hours():
    assert task_slot(at(hour=0)) == task_slot(at(hour=5, minute=59))
    assert task_slot(at(hour=6)) != task_slot(at(hour=5, minute=59))
    assert task_slot(at(hour=6)) == task_slot(at(hour=11, minute=59))
    assert task_slot(at(hour=12)) != task_slot(at(hour=11, minute=59))
    assert task_slot(at(hour=18)) != task_slot(at(hour=17, minute=59))


def test_snapshot_rotates_tasks_once_per_six_hour_slot(tmp_path):
    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            _, first = await data.snapshot("bc", 20, at(hour=12))
            first_tasks = list(first["tasks"])
            first_slot = first["task_slot"]

            _, same = await data.snapshot("bc", 20, at(hour=17, minute=59))
            assert same["task_slot"] == first_slot
            assert same["tasks"] == first_tasks

            _, rotated = await data.snapshot("bc", 20, at(hour=18))
            assert rotated["task_slot"] != first_slot
            assert len(rotated["tasks"]) == 6
            assert set(rotated["tasks"]).isdisjoint(first_tasks)
            assert rotated["done"] == []
            assert rotated["all_bonus"] is False
            specs = active_task_specs(rotated)
            assert len({spec.xp for spec in specs}) == 6
        finally:
            await db.close()

    asyncio.run(run())


def test_legacy_task_state_rotates_into_new_catalog(tmp_path):
    async def run():
        db, repo, data = await setup(tmp_path / "test.db")
        try:
            async with db.connect() as conn:
                await conn.execute(
                    """INSERT INTO adventure_days(
                        business_connection_id, chat_id, day, state
                    ) VALUES (?, ?, ?, ?)""",
                    (
                        "bc",
                        20,
                        "2026-09-20",
                        '{"tasks":["photo","words"],"done":[],"event":"","first":{},'
                        '"completed":false,"all_bonus":false,"notice_count":0,'
                        '"latest_notice":"","secret_roll":false}',
                    ),
                )
                await conn.commit()

            _, state = await data.snapshot("bc", 20, at(hour=12))
            assert len(state["tasks"]) == 6
            assert state["task_slot"] == task_slot(at(hour=12))
            assert "photo" not in state["tasks"]
            assert "words" not in state["tasks"]
        finally:
            await db.close()

    asyncio.run(run())
