from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def streak_keyboard(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(days), callback_data=f"streak_days:{days}")]
        ]
    )
