import asyncio

from app.database.activation_repository import StreakActivationRepository
from app.database.engine import Database
from app.database.repository import Repository


def test_streak_start_request_lifecycle(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)

        await repository.upsert_connection(
            "bc-1",
            owner_user_id=10,
            user_chat_id=11,
            is_enabled=True,
        )

        assert await activations.get_owner_target("bc-1") == (10, 11)

        token = await activations.create_request(
            connection_id="bc-1",
            chat_id=20,
            peer_user_id=30,
            source_message_id=40,
        )
        assert token is not None

        duplicate = await activations.create_request(
            connection_id="bc-1",
            chat_id=20,
            peer_user_id=30,
            source_message_id=41,
        )
        assert duplicate is None

        request = await activations.get_request(token)
        assert request is not None
        assert request.business_connection_id == "bc-1"
        assert request.chat_id == 20
        assert request.owner_user_id == 10
        assert request.owner_chat_id == 11
        assert request.peer_user_id == 30
        assert request.source_message_id == 40

        await activations.finish_request(token)
        assert await activations.get_request(token) is None

        await database.close()

    asyncio.run(scenario())


def test_clear_chat_allows_a_new_request(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)

        await repository.upsert_connection("bc-1", 10, 10, True)
        first = await activations.create_request(
            connection_id="bc-1",
            chat_id=20,
            peer_user_id=30,
            source_message_id=1,
        )
        assert first is not None

        await activations.clear_chat("bc-1", 20)
        second = await activations.create_request(
            connection_id="bc-1",
            chat_id=20,
            peer_user_id=30,
            source_message_id=2,
        )
        assert second is not None
        assert second != first

        await database.close()

    asyncio.run(scenario())


def test_explicit_activation_is_persisted(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)
        await repository.upsert_connection("bc-1", 10, 10, True)

        assert not await activations.is_active("bc-1", 20)
        await activations.activate("bc-1", 20)
        assert await activations.is_active("bc-1", 20)

        await database.close()

    asyncio.run(scenario())


def test_migration_keeps_real_streaks_and_drops_old_zero_rows(tmp_path):
    async def scenario():
        path = tmp_path / "test.db"
        database = Database(path)
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, 10, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=30,
            role="peer",
            today="2026-09-17",
            yesterday="2026-09-16",
            choose_pose=lambda days, last: "pose",
        )

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=21,
            message_id=2,
            peer_user_id=None,
            role="owner",
            today="2026-09-17",
            yesterday="2026-09-16",
            choose_pose=lambda days, last: "pose",
        )
        await repository.register_activity(
            connection_id="bc-1",
            chat_id=21,
            message_id=3,
            peer_user_id=30,
            role="peer",
            today="2026-09-17",
            yesterday="2026-09-16",
            choose_pose=lambda days, last: "pose",
        )
        await database.close()

        migrated = Database(path)
        await migrated.init()
        migrated_repository = Repository(migrated)
        activations = StreakActivationRepository(migrated)

        assert await migrated_repository.get_streak("bc-1", 20) is None
        assert not await activations.is_active("bc-1", 20)

        real_streak = await migrated_repository.get_streak("bc-1", 21)
        assert real_streak is not None
        assert real_streak.current_streak == 1
        assert await activations.is_active("bc-1", 21)

        await migrated.close()

    asyncio.run(scenario())
