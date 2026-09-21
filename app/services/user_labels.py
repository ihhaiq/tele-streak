from __future__ import annotations

from aiogram import Bot

from app.database.participants import account_name
from app.database.repository import Repository


async def user_label(
    bot: Bot, user_id: int, fallback: str, repository: Repository | None = None,
) -> str:
    stored = await repository.get_account_name(user_id) if repository else None
    if stored:
        return stored
    try:
        user = await bot.get_chat(user_id)
    except Exception:
        return fallback
    name = account_name(user)
    if repository:
        await repository.remember_account(user_id, name)
    return name or fallback
