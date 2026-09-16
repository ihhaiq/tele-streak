from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_path: Path
    timezone: str
    assets_dir: Path
    rendered_dir: Path


def load_settings() -> Settings:
    root = Path(__file__).resolve().parent.parent
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN is missing. Copy .env.example to .env and set BOT_TOKEN.")

    database_path = Path(os.getenv("DATABASE_PATH", str(root / "data" / "streak.db")))
    assets_dir = root / "assets" / "jake"
    rendered_dir = root / "data" / "rendered"
    database_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        database_path=database_path,
        timezone=os.getenv("TIMEZONE", "Asia/Baghdad"),
        assets_dir=assets_dir,
        rendered_dir=rendered_dir,
    )
