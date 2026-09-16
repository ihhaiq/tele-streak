# Streak Business Bot — MVP

A Telegram Business bot that tracks a daily streak for each private chat. A day completes only after both the Business account owner and the peer have sent at least one human message during the same local day.

## What this MVP does

- Handles Telegram `business_connection` updates and stores the Business owner ID.
- Handles `business_message` updates in private chats.
- Counts text, photos, video, voice, video notes, stickers, animation, files, audio, location and contacts.
- Ignores messages sent by the connected bot itself and offline/automatic Business messages.
- Requires both sides to send on the same calendar day.
- Increments only once per day.
- Resets to 1 after a missed day.
- Sends a dynamically rendered WEBP sticker through the Business connection.
- Adds a button containing the current streak number.
- Uses SQLite with WAL for the first test version.
- Includes Docker/Railway files.

## Important test-art note

`assets/jake/pose_flag.png` is a test asset based on the concept approved in the design phase. The renderer replaces the number on the flag with the current streak. The code is intentionally separated from the art so the asset can later be replaced by a final original mascot or additional poses without changing streak logic.

## Setup

1. Create a bot with `@BotFather`.
2. Configure the bot for Telegram Business / connected bots as required by Telegram and allow it to reply to messages.
3. Copy `.env.example` to `.env`.
4. Put your bot token in `BOT_TOKEN`.
5. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

6. Run:

   ```bash
   python -m app.main
   ```

7. Connect the bot to the Telegram Business account.
8. Test in a private chat:
   - Peer sends one normal message.
   - Business account owner sends one normal message.
   - Once both sides have sent during the same Baghdad calendar day, the bot sends the streak sticker into that chat.

## Docker

```bash
docker build -t streak-business-bot .
docker run --env-file .env streak-business-bot
```

## Railway

Set at least:

- `BOT_TOKEN`
- `TIMEZONE=Asia/Baghdad`

The default SQLite DB is stored at `data/streak.db`. On Railway, SQLite is ephemeral unless you mount a persistent Volume. For long-term deployment, use a Railway Volume or migrate the repository layer to PostgreSQL.

## Streak rules

For local day D:

- owner sent + peer did not send => no completion
- peer sent + owner did not send => no completion
- both sent => exactly one completion
- repeated messages => no extra increments
- if previous completed day was D-1 => `streak += 1`
- otherwise => `streak = 1`

## Useful bot commands

- `/start` — setup reminder
- `/status` — active Business connections + number of tracked chats


## Asset engine and local sticker pack

At startup the bot prepares a reusable local pack for streak values **1 through 250** in
`data/rendered/`. Existing WEBP files are reused, so they are rendered only on the
first run (or when a source asset changes). Generated stickers are intentionally
ignored by Git.

Pose definitions are discovered recursively under `assets/jake/`. To add a pose,
place a transparent PNG and a JSON file beside it:

```json
{
  "id": "hug",
  "image": "hug.png",
  "category": "normal",
  "number_box": [0.19, 0.075, 0.76, 0.285],
  "font_size": 120,
  "rotation": -4,
  "weight": 1.0,
  "max_digits": 5
}
```

Supported categories are `normal`, `waiting`, `milestone`, `rare`, and
`broken`. Milestone JSON can also contain `"milestones": [7, 30, 100]`.
The selector avoids using the same pose twice in a row when an alternative exists.

## Chat command

Either participant can send `ستريك` in the Business chat to view the current
streak, longest streak, and last completed day. The query itself is not counted
as daily streak activity.
