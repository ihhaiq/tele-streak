import asyncio

from app.database.adventure_repository import AdventureRepository
from app.database.engine import Database
from app.database.repository import Repository


def test_story_publish_request_is_authorized_single_use_and_persistent(tmp_path):
    async def run():
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
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )
        await repository.register_activity(
            connection_id="bc-1",
            chat_id=20,
            message_id=2,
            peer_user_id=30,
            role="peer",
            today="2026-09-20",
            yesterday="2026-09-19",
            choose_pose=lambda days, last: "pose",
        )

        adventures = AdventureRepository(database)
        request, old_paths = await adventures.create_story_publish_request(
            connection_id="bc-1",
            chat_id=20,
            owner_user_id=10,
            kind="video5",
            media_path="/tmp/story.mp4",
            thumbnail_path="/tmp/story.jpg",
            days=7,
            ttl_seconds=900,
        )
        assert old_paths == []
        assert len(request.token) <= 32

        status, _ = await adventures.claim_story_publish(request.token, 999)
        assert status == "unauthorized"

        status, claimed = await adventures.claim_story_publish(request.token, 30)
        assert status == "ready"
        assert claimed is not None and claimed.kind == "video5"

        status, _ = await adventures.claim_story_publish(request.token, 10)
        assert status == "publishing"

        await adventures.release_story_publish(request.token)
        status, _ = await adventures.claim_story_publish(request.token, 10)
        assert status == "ready"

        await adventures.complete_story_publish(request.token, 55)
        stored = await adventures.get_story_publish_request(request.token)
        assert stored is not None
        assert stored.status == "published"
        assert stored.published_story_id == 55

        status, published = await adventures.claim_story_publish(request.token, 30)
        assert status == "published"
        assert published is not None and published.published_story_id == 55

        paths = await adventures.delete_story_publish_request(request.token)
        assert set(paths) == {"/tmp/story.mp4", "/tmp/story.jpg"}
        assert await adventures.get_story_publish_request(request.token) is None
        await database.close()

    asyncio.run(run())


def test_new_story_preview_replaces_old_pending_request(tmp_path):
    async def run():
        database = Database(tmp_path / "test.db")
        await database.init()
        repository = Repository(database)
        await repository.upsert_connection("bc-1", 10, None, True)
        adventures = AdventureRepository(database)

        first, _ = await adventures.create_story_publish_request(
            connection_id="bc-1",
            chat_id=20,
            owner_user_id=10,
            kind="image",
            media_path="/tmp/old.jpg",
            thumbnail_path="/tmp/old.jpg",
            days=1,
        )
        second, old_paths = await adventures.create_story_publish_request(
            connection_id="bc-1",
            chat_id=20,
            owner_user_id=10,
            kind="image",
            media_path="/tmp/new.jpg",
            thumbnail_path="/tmp/new.jpg",
            days=2,
        )

        assert await adventures.get_story_publish_request(first.token) is None
        assert await adventures.get_story_publish_request(second.token) is not None
        assert "/tmp/old.jpg" in old_paths
        await database.close()

    asyncio.run(run())
