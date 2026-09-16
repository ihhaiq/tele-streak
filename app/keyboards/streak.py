from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def streak_keyboard(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔥 {days}", callback_data=f"streak_days:{days}")]
        ]
    )


def revive_streak_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧊 إحياء الستريك", callback_data="streak:revive")]
        ]
    )
