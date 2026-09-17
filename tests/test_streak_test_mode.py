import asyncio

from app.database.engine import Database
from app.database.repository import Repository
from app.handlers.streak_test import parse_streak_test_query
from app.services.streak_test_service import StreakTestService


def test_streak_test_command_parser():
    assert parse_streak_test_query("اختبار ستريك") == "help"
    assert parse_streak_test_query("اختبار ستريك نجاح") == "success"
    assert parse_streak_test_query("اختبار ستريك حالة") == "status"
    assert parse_streak_test_query("اختبار ستريك تحذير") == "warning"
    assert parse_streak_test_query("اختبار ستريك خسارة") == "broken"
    assert parse_streak_test_query("اختبار ستريك إحياء") == "revive"
    assert parse_streak_test_query("اختبار ستريك الكل") == "all"
    assert parse_streak_test_query("/streaktest revive") == "revive"
    assert parse_streak_test_query("اختبار ستريك شيء") == "invalid"
    assert parse_streak_test_query("ستريك") is None


def test_revive_test_requires_two_people_without_mutating_streak(tmp_path):
    async def scenario():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        tests = StreakTestService(repository)
        await repository.upsert_connection("bc-1", 10, None, True)

        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=1,
            peer_user_id=None,
            role="owner",
            today="2026-09-17",
            yesterday="2026-09-16",
            choose_pose=lambda days, last: "pose",
        )
        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-17",
            yesterday="2026-09-16",
            choose_pose=lambda days, last: "pose",
        )

        before = await repository.get_streak("bc-1", 20)
        assert before is not None
        assert before.current_streak == 1
        assert before.freeze_count == 3

        request = await tests.create_revive_test("bc-1", 20)
        assert request is not None

        outsider = await tests.approve(request.token, 999)
        assert outsider.status == "unauthorized"
        assert not outsider.ready

        owner = await tests.approve(request.token, 10)
        assert owner.status == "approved"
        assert not owner.ready

        owner_again = await tests.approve(request.token, 10)
        assert owner_again.status == "already"
        assert not owner_again.ready

        peer = await tests.approve(request.token, 30)
        assert peer.status == "approved"
        assert peer.ready

        after = await repository.get_streak("bc-1", 20)
        assert after is not None
        assert after.current_streak == before.current_streak
        assert after.freeze_count == before.freeze_count
        assert after.break_count == before.break_count

        await database.close()

    asyncio.run(scenario())
