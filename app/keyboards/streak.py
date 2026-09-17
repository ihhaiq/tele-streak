from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def streak_keyboard(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🔥 {days}", callback_data=f"streak_days:{days}")]
        ]
    )


def revive_streak_keyboard(action_token: str | None = None) -> InlineKeyboardMarkup:
    callback_data = (
        f"streak:revive:{action_token}"
        if action_token
        else "streak:revive"
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧊 إحياء الستريك", callback_data=callback_data)]
        ]
    )


def start_request_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔥 بدء الستريك",
                    callback_data=f"streak_start:approve:{token}",
                )
            ]
        ]
    )
