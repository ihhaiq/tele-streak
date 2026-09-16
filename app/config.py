from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FIRE_EFFECT_ID = "5107584321108051014"


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    timezone: str
    assets_dir: Path
    ready_stickers_dir: Path
    rendered_dir: Path
    message_effect_id: str | None
    sticker_set_owner_id: int | None
    sticker_set_title: str


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.")

    database_path = Path(os.getenv("DATABASE_PATH", str(root / "data" / "streak.db")))
    assets_dir = root / "assets" / "jake"
    ready_stickers_dir = root / "assets" / "streak_stickers" / "jake" / "ready"
    rendered_dir = root / "data" / "rendered"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_dir.mkdir(parents=True, exist_ok=True)

    effect_id = os.getenv("MESSAGE_EFFECT_ID", DEFAULT_FIRE_EFFECT_ID).strip()
    return Settings(
        bot_token=token,
        database_path=database_path,
        timezone=os.getenv("TIMEZONE", "Asia/Baghdad"),
        assets_dir=assets_dir,
        ready_stickers_dir=ready_stickers_dir,
        rendered_dir=rendered_dir,
        message_effect_id=effect_id or None,
        sticker_set_owner_id=_optional_int("STICKER_SET_OWNER_ID"),
        sticker_set_title=os.getenv("STICKER_SET_TITLE", "Jake Streak").strip()
        or "Jake Streak",
    )
