import asyncio

from app.database.engine import Database
from app.database.repository import Repository
from app.database.revive_request_repository import ReviveRequestRepository


def test_revive_requires_both_streak_participants(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        approvals = ReviveRequestRepository(database)
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
        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: "pose",
        )
        assert await repository.process_missed_day(
            connection_id="bc-1",
            chat_id=20,
            today="2026-09-18",
            missed_day="2026-09-17",
            day_before_missed="2026-09-16",
        ) == "broken"

        request = await approvals.create_or_get("bc-1", 20)
        assert request is not None
        assert not request.owner_approved
        assert not request.peer_approved

        outsider = await approvals.approve(request.token, 999)
        assert outsider.status == "unauthorized"
        assert not outsider.ready

        owner = await approvals.approve(request.token, 10)
        assert owner.status == "approved"
        assert owner.state is not None
        assert owner.state.owner_approved
        assert not owner.state.peer_approved
        assert not owner.ready

        owner_again = await approvals.approve(request.token, 10)
        assert owner_again.status == "already"
        assert not owner_again.ready

        peer = await approvals.approve(request.token, 30)
        assert peer.status == "approved"
        assert peer.state is not None
        assert peer.state.owner_approved
        assert peer.state.peer_approved
        assert peer.ready

        revived = await repository.revive_streak("bc-1", 20)
        assert revived.status == "revived"
        assert revived.streak == 1

        completed = await approvals.approve(request.token, 30)
        assert completed.status == "completed"

        await database.close()

    asyncio.run(scenario())


def test_revive_request_is_unavailable_before_streak_breaks(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        approvals = ReviveRequestRepository(database)
        await repository.upsert_connection("bc-1", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=30,
            role="peer",
            today="2026-09-16",
            yesterday="2026-09-15",
            choose_pose=lambda days, last: "pose",
        )

        assert await approvals.create_or_get("bc-1", 20) is None
        await database.close()

    asyncio.run(scenario())
