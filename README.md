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

The bot does not store message text, photos, videos, or files. It stores only
connection/chat identifiers, participant identifiers, daily activity dates,
streak counters, selected pose data, and the last success-message ID.


## Dashboard and settings

The private `/start` dashboard shows Business connection status, active chats,
current/highest streaks, completed days, Freeze usage, and the best streak chat.
It also supports timezone selection and per-chat enable/disable, reset,
notification mute, and automatic-Freeze controls.
