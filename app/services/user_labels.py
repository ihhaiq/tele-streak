from __future__ import annotations

from aiogram import Bot


async def user_label(bot: Bot, user_id: int, fallback: str) -> str:
    """Return a readable account name without making names part of streak state."""
    try:
        user = await bot.get_chat(user_id)
    except Exception:
        return fallback
    name = getattr(user, "full_name", None) or getattr(user, "title", None)
    username = getattr(user, "username", None)
    if name and username:
        return f"{name} (@{username})"
    return name or (f"@{username}" if username else fallback)
