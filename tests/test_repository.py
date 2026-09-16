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

    asyncio.run(scenario())


def test_freeze_is_awarded_at_thirty_days(tmp_path):
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
        assert record.freeze_count == 1

    asyncio.run(scenario())
