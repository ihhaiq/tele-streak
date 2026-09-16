from __future__ import annotations

from aiogram import Router
from aiogram.types import BusinessConnection

from app.database.repository import Repository


def build_router(repository: Repository) -> Router:
    router = Router(name="business_connection")

    @router.business_connection()
    async def on_business_connection(connection: BusinessConnection) -> None:
        await repository.upsert_connection(
            connection_id=connection.id,
            owner_user_id=connection.user.id,
            user_chat_id=connection.user_chat_id,
            is_enabled=connection.is_enabled,
        )

    return router
