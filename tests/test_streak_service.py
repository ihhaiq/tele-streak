import asyncio
from types import SimpleNamespace

from app.database.activation_repository import StreakActivationRepository
from app.database.engine import Database
from app.database.repository import Repository
from app.services.streak_service import StreakService


class FakePoses:
    def choose(self, days, last_pose):
        return SimpleNamespace(id=f"pose-{days}")


def message(connection_id: str, chat_id: int, sender_id: int, message_id: int):
    return SimpleNamespace(
        business_connection_id=connection_id,
        chat=SimpleNamespace(id=chat_id),
        from_user=SimpleNamespace(id=sender_id),
        message_id=message_id,
        text="هلا",
    )


def make_service(database: Database, repository: Repository) -> StreakService:
    return StreakService(
        repository,
        StreakActivationRepository(database),
        "Asia/Baghdad",
        FakePoses(),
    )


def test_normal_messages_do_not_auto_start_streak(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)
        await repository.upsert_connection("bc-1", 10, 10, True)
        service = make_service(database, repository)

        owner_message = message("bc-1", 20, 10, 1)
        result = await service.register_message(owner_message)
        assert not result.completed
        assert await repository.get_streak("bc-1", 20) is None
        assert not await activations.is_active("bc-1", 20)

        await database.close()

    asyncio.run(scenario())


def test_owner_start_counts_owner_then_waits_for_peer(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)
        await repository.upsert_connection("bc-1", 10, 10, True)
        service = make_service(database, repository)

        start = await service.start_by_owner(message("bc-1", 20, 10, 1))
        assert not start.completed
        assert await activations.is_active("bc-1", 20)
        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.owner_sent_day is not None
        assert record.peer_sent_day is None

        completion = await service.register_message(message("bc-1", 20, 30, 2))
        assert completion.completed
        assert completion.days == 1
        assert completion.pose == "pose-1"

        await database.close()

    asyncio.run(scenario())


def test_approved_peer_request_counts_peer_then_waits_for_owner(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)
        await repository.upsert_connection("bc-1", 10, 10, True)
        service = make_service(database, repository)

        start = await service.start_from_peer_request(
            connection_id="bc-1",
            chat_id=20,
            peer_user_id=30,
            source_message_id=1,
        )
        assert not start.completed
        assert await activations.is_active("bc-1", 20)
        record = await repository.get_streak("bc-1", 20)
        assert record is not None
        assert record.owner_sent_day is None
        assert record.peer_sent_day is not None

        completion = await service.register_message(message("bc-1", 20, 10, 2))
        assert completion.completed
        assert completion.days == 1

        await database.close()

    asyncio.run(scenario())


def test_stale_message_connection_can_use_latest_owner_connection(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import app.services.streak_service as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 18, 12, tzinfo=ZoneInfo("Asia/Baghdad")).astimezone(tz)

    monkeypatch.setattr(module, "datetime", Clock)
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        activations = StreakActivationRepository(database)

        await repository.upsert_connection("bc-old", 10, 10, True)
        await activations.activate("bc-old", 20)
        await repository.register_activity(
            connection_id="bc-old",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-18",
            yesterday="2026-09-17",
            choose_pose=lambda days, last: "pose",
        )
        await repository.upsert_connection("bc-old", 10, 10, False)
        await repository.upsert_connection("bc-new", 10, 10, True)

        service = make_service(database, repository)
        stale = message("bc-old", 20, 30, 2)
        completion = await service.register_message(
            stale,
            connection_id="bc-new",
        )

        assert completion.completed
        assert completion.days == 1
        record = await repository.get_streak("bc-new", 20)
        assert record is not None
        assert record.peer_user_id == 30
        assert await repository.get_streak("bc-old", 20) is None

        await database.close()

    asyncio.run(scenario())
