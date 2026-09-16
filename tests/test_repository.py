import asyncio

from app.database.engine import Database
from app.database.repository import Repository


def test_activity_is_atomic_and_duplicate_safe(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        owner = await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: f"pose-{days}",
        )
        assert not owner.completed

        duplicate = await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: f"pose-{days}",
        )
        assert duplicate.duplicate

        peer = await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: f"pose-{days}",
        )
        assert peer.completed
        assert peer.days == 1
        assert peer.pose_id == "pose-1"

        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.current_streak == 1
        assert record.longest_streak == 1
        assert record.completed_days == 1
        assert record.freeze_count == 3
        assert record.auto_freeze is False

        await database.close()

    asyncio.run(scenario())


def test_freeze_balance_stays_capped_at_three(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        for day in range(1, 31):
            today = f"2026-01-{day:02}"
            previous = f"2026-01-{day - 1:02}" if day > 1 else "2025-12-31"
            await repository.register_activity(
                connection_id="bc-1",
                chat_id=20,
                message_id=day * 2,
                peer_user_id=None,
                role="owner",
                today=today,
                yesterday=previous,
                choose_pose=lambda days, last: "pose",
            )
            await repository.register_activity(
                connection_id="bc-1",
                chat_id=20,
                message_id=day * 2 + 1,
                peer_user_id=30,
                role="peer",
                today=today,
                yesterday=previous,
                choose_pose=lambda days, last: "pose",
            )

        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.current_streak == 30
        assert record.freeze_count == 3

        await database.close()

    asyncio.run(scenario())




def test_broken_streak_can_be_revived_once_with_protection(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: "pose",
        )
        completed = await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: "pose",
        )
        assert completed.completed

        broken = await repository.process_missed_day(
            connection_id="bc-1",
            chat_id=20,
            today="2026-09-18",
            missed_day="2026-09-17",
            day_before_missed="2026-09-16",
        )
        assert broken == "broken"

        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.current_streak == 0
        assert record.break_count == 1
        assert record.freeze_count == 3

        revived = await repository.revive_streak("bc-1", 20)
        assert revived.status == "revived"
        assert revived.streak == 1
        assert revived.freeze_count == 2

        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.current_streak == 1
        assert record.break_count == 0
        assert record.freeze_count == 2
        assert record.freezes_used == 1
        assert record.last_completed_day == "2026-09-17"

        second = await repository.revive_streak("bc-1", 20)
        assert second.status == "unavailable"

        await database.close()

    asyncio.run(scenario())

def test_timezone_and_chat_controls(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        assert await repository.get_connection_timezone("bc-1") == "Asia/Baghdad"
        assert await repository.set_owner_timezone(10, "UTC") == 1
        assert await repository.get_connection_timezone("bc-1") == "UTC"

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: "pose",
        )
        assert await repository.toggle_chat_setting(10, 20, "enabled") is False
        streak = await repository.get_owner_streak(10, 20)
        assert streak is not None
        assert streak.is_enabled is False
        assert await repository.reset_streak(10, 20)

        await database.close()

    asyncio.run(scenario())



def test_guest_streak_request_is_one_time(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-guest", 10, None, True)

        token = await repository.create_guest_streak_request(
            "bc-guest",
            20,
            ttl_seconds=120,
        )
        assert token
        await repository.set_guest_streak_summon_message(token, 99)

        request = await repository.consume_guest_streak_request(token)
        assert request is not None
        assert request.business_connection_id == "bc-guest"
        assert request.chat_id == 20
        assert request.summon_message_id == 99

        duplicate = await repository.consume_guest_streak_request(token)
        assert duplicate is None

        await database.close()

    asyncio.run(scenario())
