import json
import sqlite3
from pathlib import Path
from dataclasses import asdict
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.adventures.rules import Activity, Profile
from app.adventures.tasks import TASK_CATALOG, task_label
from app.adventures.views import page_text, rich_page
from app.database.activation_repository import StreakActivationRepository
from app.database.adventure_repository import AdventureRepository
from app.database.engine import Database
from app.database.repository import Repository
from app.services.rich_status import build_streak_fallback_text, build_streak_rich_message, participation_text
from app.services.streak_service import StreakService
from app.services.user_labels import user_label


async def setup(path):
    db = Database(path)
    await db.init()
    repo = Repository(db)
    await repo.upsert_connection("bc", 10, 10, True)
    await StreakActivationRepository(db).activate("bc", 20)
    return db, repo


async def send(repo, mid, role="owner", name="حسين", day="2026-09-21", qualifies=True):
    now = datetime.fromisoformat(day).replace(hour=12, tzinfo=ZoneInfo("Asia/Baghdad"))
    return await repo.register_activity(
        connection_id="bc", chat_id=20, message_id=mid,
        peer_user_id=20 if role == "peer" else None, role=role,
        today=day, yesterday=(now.date() - timedelta(days=1)).isoformat(),
        choose_pose=lambda *_: "pose", qualifies=qualifies,
        adventure=Activity(now, role, words=3, name=name, qualifies=qualifies),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["owner", "peer"])
async def test_private_waiting_completion_and_restart(tmp_path, monkeypatch, first):
    monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-21")
    path = tmp_path / "db.sqlite"
    db, repo = await setup(path)
    try:
        await repo.remember_account(10, "حسين")
        await repo.remember_account(20, "أحمد")
        names = {"owner": "حسين", "peer": "أحمد"}
        second = "peer" if first == "owner" else "owner"
        result = await send(repo, 1, first, names[first])
        assert not result.completed
        record = await repo.get_streak("bc", 20)
        progress = await repo.participant_status(record)
        text = participation_text(**progress)
        assert f"✅ أكمل اليوم: {names[first]}" in text
        assert f"⏳ بانتظار: {names[second]}" in text
        assert record.last_contributor_user_id == (10 if first == "owner" else 20)
        assert record.last_contributor_name == names[first]
        # إعادة الإرسال ونوع غير مطابق ما يكملان الشرط عن الشخص المنتظر.
        assert not (await send(repo, 2, first, names[first])).completed
        assert not (await send(repo, 3, second, names[second], qualifies=False)).completed
        assert (await repo.get_streak("bc", 20)).last_contributor_name == names[first]
        result = await send(repo, 4, second, names[second])
        assert result.completed and result.days == 1
        assert not (await send(repo, 5, first, names[first])).completed
        record = await repo.get_streak("bc", 20)
        assert record.last_contributor_name == names[second]
        assert record.last_contribution_day == "2026-09-21"
        profile, _ = await AdventureRepository(db).snapshot("bc", 20, datetime(2026, 9, 21, 12))
        assert profile.shared_xp > 0 and profile.combo == 1
        assert profile.stats["owner"]["days"] == profile.stats["peer"]["days"] == 1
    finally:
        await db.close()
    db = Database(path)
    await db.init()
    try:
        repo = Repository(db)
        record = await repo.get_streak("bc", 20)
        progress = await repo.participant_status(record)
        assert participation_text(**progress) == "✅ اكتمل اليوم بواسطة:\nحسين وأحمد"
        values = dict(current=1, longest=1, completed_days=1, break_count=0,
                      freeze_count=3, last_completed_day="2026-09-21", **progress)
        assert "حسين وأحمد" in build_streak_fallback_text(**values)
        assert "حسين وأحمد" in build_streak_rich_message(**values, owner_user_id=10, chat_id=20).html
        await repo.upsert_connection("bc-new", 10, 10, True)
        moved = await repo.get_streak("bc-new", 20)
        assert moved.last_contributor_name == names[second]
        assert await repo.participant_status(moved) == progress
        monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-22")
        assert participation_text(**progress) == "⏳ بانتظار: حسين وأحمد"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_missing_names_keep_ids_and_fallback_and_do_not_erase_known_names(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-21")
    db, repo = await setup(tmp_path / "db.sqlite")
    try:
        await send(repo, 1, name="")
        record = await repo.get_streak("bc", 20)
        assert record.last_contributor_user_id == 10 and record.last_contributor_name is None
        text = participation_text(**await repo.participant_status(record))
        assert "✅ أكمل اليوم: الطرف الأول" in text and "⏳ بانتظار: الطرف الثاني" in text
        await repo.remember_account(10, "حسين <&>")
        await repo.remember_account(10, "")
        assert await repo.get_account_name(10) == "حسين <&>"
        bot = SimpleNamespace(get_chat=AsyncMock(side_effect=RuntimeError("unavailable")))
        assert await user_label(bot, 10, "الطرف الأول", repo) == "حسين <&>"
        assert await user_label(bot, 20, "الطرف الثاني", repo) == "الطرف الثاني"
        values = dict(current=0, longest=0, completed_days=0, break_count=0, freeze_count=3,
                      last_completed_day=None, **await repo.participant_status(record))
        rich = build_streak_rich_message(**values, owner_user_id=10, chat_id=20)
        assert "حسين &lt;&amp;&gt;" in rich.html
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_start_message_saves_both_account_names_before_peer_sends(tmp_path):
    db, repo = await setup(tmp_path / "db.sqlite")
    try:
        service = StreakService(repo, StreakActivationRepository(db), "Asia/Baghdad",
                                SimpleNamespace(choose=lambda *_: SimpleNamespace(id="pose")))
        message = SimpleNamespace(business_connection_id="bc", message_id=1,
                                  from_user=SimpleNamespace(id=10, full_name="حسين"),
                                  chat=SimpleNamespace(id=20, full_name="أحمد"))
        await service.start_by_owner(message)
        progress = await repo.participant_status(await repo.get_streak("bc", 20))
        assert progress["owner_name"] == "حسين" and progress["peer_name"] == "أحمد"
    finally:
        await db.close()


@pytest.mark.parametrize("spec", TASK_CATALOG.values(), ids=lambda spec: spec.key)
def test_all_task_labels_name_the_assigned_accounts(spec):
    text = task_label(spec, "حسين", "أحمد")
    assert "الطرف الأول" not in text and "الطرف الثاني" not in text
    if spec.role == "owner":
        assert "حسين" in text and "أحمد" not in text
    elif spec.role == "peer":
        assert "أحمد" in text and "حسين" not in text
    else:
        assert "حسين" in text and "أحمد" in text


def test_task_renderers_escape_names_and_use_fallback():
    profile = Profile()
    state = {"tasks": ["owner_messages_1", "both_messages_1", "pair_photo_voice"], "done": []}
    assert "الطرف الأول" in page_text(profile, state, "tasks")
    profile.stats["owner"]["name"] = "حسين <&>"
    profile.stats["peer"]["name"] = "أحمد"
    assert "حسين <&> وأحمد" in page_text(profile, state, "tasks")
    html = rich_page(profile, state, "tasks", 10, 20).html
    assert "حسين &lt;&amp;&gt;" in html and "الطرف الأول" not in html


@pytest.mark.asyncio
async def test_migration_preserves_old_records_and_legacy_names(tmp_path):
    # نبني قاعدة من schema الرئيسي قبل الإصلاح، ثم نعيد الترقية مرتين.
    schema = (Path(__file__).parent / "fixtures/pre_participant_names.sql").read_text()
    from app.database.adventure_repository import SCHEMA as adventure_schema
    path = tmp_path / "legacy.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(schema + adventure_schema)
    connection.execute("INSERT INTO business_connections VALUES ('bc',10,10,1,'Asia/Baghdad','old')")
    connection.execute("""INSERT INTO streaks(business_connection_id,chat_id,peer_user_id,
                       current_streak,longest_streak,completed_days,last_completed_day,created_at,updated_at)
                       VALUES ('bc',20,20,7,9,10,'2026-09-20','old','old')""")
    profile = Profile(shared_xp=123)
    profile.stats["owner"]["name"] = "حسين"
    profile.stats["peer"]["name"] = "أحمد"
    connection.execute("INSERT INTO adventure_profiles VALUES ('bc',20,123,1,?,0)",
                       (json.dumps(asdict(profile)),))
    connection.commit()
    connection.close()
    db = Database(path)
    try:
        await db.init()
        await db.init()
        repo = Repository(db)
        record = await repo.get_streak("bc", 20)
        assert (record.current_streak, record.longest_streak, record.completed_days) == (7, 9, 10)
        assert record.last_contributor_user_id is None
        names = await repo.participant_status(record)
        assert names["owner_name"] == "حسين" and names["peer_name"] == "أحمد"
        p, _ = await AdventureRepository(db).snapshot("bc", 20, datetime(2026, 9, 21, 12))
        assert p.shared_xp == 123
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_mode_change_and_reset_clear_only_pending_contribution(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-21")
    db, repo = await setup(tmp_path / "db.sqlite")
    try:
        await send(repo, 1)
        record = await repo.set_streak_mode(10, "bc", 20, "voice", "2026-09-21")
        assert record.last_contributor_user_id is None
        assert record.owner_sent_day is None and record.peer_sent_day is None
        assert "✅ أكمل اليوم" not in participation_text(**await repo.participant_status(record))
        await send(repo, 2)
        await send(repo, 3, "peer", "أحمد")
        record = await repo.set_streak_mode(10, "bc", 20, "message", "2026-09-21")
        assert record.last_contributor_user_id == 20
        assert "حسين وأحمد" in participation_text(**await repo.participant_status(record))
        await repo.reset_streak(10, 20)
        record = await repo.get_streak("bc", 20)
        assert record.last_contributor_user_id is None and record.last_contribution_day is None
        assert (await repo.participant_status(record))["owner_name"] == "حسين"
    finally:
        await db.close()


def test_protected_day_is_not_reported_as_both_people_sending(monkeypatch):
    monkeypatch.setattr("app.services.rich_status.current_day", lambda _: "2026-09-21")
    text = build_streak_fallback_text(
        current=7, longest=7, completed_days=6, break_count=0, freeze_count=2,
        last_completed_day="2026-09-21", owner_sent_day="2026-09-20",
        peer_sent_day="2026-09-20", owner_name="حسين", peer_name="أحمد",
    )
    assert "✅ اكتمل اليوم بواسطة" not in text
    assert "⏳ بانتظار: حسين وأحمد" in text
