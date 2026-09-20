# Streak Business Bot

Telegram Business bot that maintains an independent daily streak for each
`business_connection_id + chat_id`. A day completes only after the Business
account owner and the peer each send at least one human message during the same
local day.

## Current features

- Tracks private Business chats independently.
- Counts a sender only once per local day.
- Ignores bot-generated and automatic Business messages.
- Commits streak completion before attempting to send Telegram media.
- Prevents duplicate completion with an atomic SQLite transaction.
- Stores current and longest streak values.
- Sends Jake WEBP stickers for streaks `1–250` from three Telegram packs.
- Creates and synchronizes a real Telegram sticker set on first streak use.
- Adds Telegram's animated fire effect to streak status and success messages.
- Falls back to the metadata-driven renderer when ready art is unavailable.
- Adds an inline button formatted as `🔥 N`.
- Lets either participant send `ستريك` to view current status without counting
  that query as streak activity.
- Includes special `warning.webp` and `broken.webp` artwork for upcoming
  reminder and break-detection features.

## Project status

The repository includes reviewed ready stickers `1–60` plus a 30-pose positive-expression sprite source. On first use, the bot builds missing `61–250` WebP files once and synchronizes three Telegram packs (Telegram allows 120 stickers per pack). Warning and broken-streak stickers are included in the third pack. Upload progress is inferred from each pack's current size, so a restart resumes instead of starting over.

## Setup

1. Create and configure a Telegram Business bot with `@BotFather`.
2. Copy `.env.example` to `.env`.
3. Set `BOT_TOKEN`.
4. Install and run:

   ```bash
   pip install -r requirements.txt
   python -m app.main
   ```

5. Connect the bot to the Telegram Business account.
6. In a private chat, let the peer and owner each send one normal message. The
   bot creates/synchronizes the sticker set on first use, then sends its numbered
   sticker after both have participated.

Optional settings:

- `MESSAGE_EFFECT_ID` — fire effect ID; leave empty to disable effects.
- `STICKER_SET_OWNER_ID` — required numeric developer Telegram ID. The three
  packs are global and shared by all bot users; ownership never follows users.
- `STICKER_SET_TITLE` — visible Telegram sticker-set title.

## Commands

- `/start` — setup information.
- `/status` — connection and tracked-chat counts.
- `ستريك` — current streak, longest streak, and last completed day.

## Streak rules

For local day D:

- Owner only or peer only: no completion.
- Both participants: exactly one completion.
- Repeated messages: no additional increment.
- Previous completion on D-1: increment.
- Any missed complete day: restart at 1 on the next completed day.

## Sticker assets

All committed art is normalized so the drawing fills the 512x512 frame instead
of sitting small in the middle. `tools/upscale_stickers.py` crops to the real
artwork, drops fragments that bled in from neighbouring sprite-sheet cells,
rescales with LANCZOS plus a light unsharp pass, and re-encodes under
Telegram's 512 KB limit:

```bash
python -m tools.upscale_stickers --check   # report only
python -m tools.upscale_stickers           # rewrite in place
```

The same fitting step (`app/stickers/canvas.py`) runs inside the fallback
renderer and the `61-250` pack builder, so newly generated art comes out at the
same scale. `tests/test_canvas.py` and `tests/test_sticker_pack.py` guard both
the fit and the bleed removal.


Reviewed numbered stickers live at:

```text
assets/streak_stickers/jake/ready/001.webp
...
assets/streak_stickers/jake/ready/250.webp
```

Special artwork lives under:

```text
assets/streak_stickers/jake/special/
  warning.webp
  broken.webp
```

Every committed sticker is a transparent `512×512` WebP below Telegram's
static-sticker size limit. Tests verify numbering, dimensions, format, and
special asset presence.

The fallback renderer reads pose metadata recursively from `assets/jake/`.
A new fallback pose requires only a PNG and adjacent JSON metadata file. Ready
numbered art always takes priority.

## Performance notes

- SQLite runs on one long-lived connection guarded by an asyncio lock instead
  of opening a connection per query; a completed-message round trip drops from
  roughly 2.4 ms to 0.3 ms.
- `synchronous=NORMAL`, a 16 MB page cache, `temp_store=MEMORY` and `mmap_size`
  are set once at startup.
- Connection owners are cached in memory (bounded LRU), removing one query per
  incoming Business message, and invalidated when a connection event arrives.
- Per-chat asyncio locks are released once idle instead of accumulating.
- Pose lookup is a dict, and category buckets are computed once at load.
- Fonts are cached with `lru_cache` instead of being reopened per render.
- `uvloop` is used when installed; `python -m app.main` falls back to asyncio.
- The bot session and the database are closed on shutdown.

## Docker

```bash
docker build -t streak-business-bot .
docker run --env-file .env streak-business-bot
```

## Railway and storage

Set at least:

- `BOT_TOKEN`
- `TIMEZONE=Asia/Baghdad`

SQLite defaults to `data/streak.db`. Railway's filesystem is ephemeral unless
a persistent Volume is mounted. The committed sticker pack does not need a
Volume; database persistence does.

## Privacy

The bot does not permanently store message text, photos, videos, or files. Story
rendering uses temporary profile photos and video files, deleted after delivery.
It stores display names, shared progression and daily mission metadata, plus
connection/chat identifiers, participant identifiers, daily activity dates,
streak counters, selected pose data, and the last success-message ID.


## Dashboard and settings

The private `/start` dashboard shows Business connection status, active chats,
current/highest streaks, completed days, Freeze usage, and the best streak chat.
It also supports timezone selection and per-chat enable/disable, reset,
notification mute, and automatic-Freeze controls.

## Shared adventures and story sharing

Each pair now has shared XP/level, daily missions, a friendly comparison,
Combo bonuses, occasional events, unlockable achievements, and a number-free
Jake celebration on the first completed day of a new streak. Open `ستريك`
for the new buttons. Existing streak content modes still decide daily completion.

`مشاركة ستوري` offers the requested 720×1280 still PNG first, with Jake playing
with profile-photo balls, both names, and the streak length. A 5- or 10-second
animated MP4 remains as an optional extra. Docker includes FFmpeg and Arabic
text shaping. Set `STORY_MUSIC_PATH` to a local song for the video if desired;
an original instrumental celebration melody is included by default.

See [the implementation and operations guide](docs/ADVENTURES.md) for the data
model, reward rules, migration behavior, testing, and deployment checks.


### Native Telegram story editor

When a public HTTPS domain and Telegram Main Mini App are configured, the story
format buttons open Telegram's native story editor instead of only sending the
generated file into the Business chat. The user still reviews the story and
presses Publish; the bot never posts a personal story without that final action.

Deployment:

1. Give the Railway service a public domain. The bot automatically uses
   `RAILWAY_PUBLIC_DOMAIN`, or set `PUBLIC_BASE_URL=https://your-domain`.
2. In @BotFather open **Bot Settings > Configure Mini App > Enable Mini App**
   and set the Main Mini App URL to `https://your-domain/story/app`.
3. Restart the bot after enabling the Main Mini App so `getMe` reports
   `has_main_web_app=true`.

Story links are signed, expire after `STORY_SHARE_TTL_SECONDS` (15 minutes by
default), and the backend validates Telegram Mini App init data plus the opening
user. Only the two streak participants can prepare the media. Generated share
files are temporary and are deleted after expiry. If the Main Mini App is not
configured, the previous send-photo/send-video flow remains available.
