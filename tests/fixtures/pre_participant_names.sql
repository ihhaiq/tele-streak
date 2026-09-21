-- SQLite schema from main 3112254, before participant-name migrations.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS business_connections (
    business_connection_id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL,
    user_chat_id INTEGER,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    timezone TEXT NOT NULL DEFAULT 'Asia/Baghdad',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_streaks (
    channel_id INTEGER PRIMARY KEY,
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    completed_days INTEGER NOT NULL DEFAULT 0,
    break_count INTEGER NOT NULL DEFAULT 0,
    last_completed_day TEXT,
    last_completed_by TEXT,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS streaks (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    peer_user_id INTEGER,
    streak_mode TEXT NOT NULL DEFAULT 'message',
    current_streak INTEGER NOT NULL DEFAULT 0,
    longest_streak INTEGER NOT NULL DEFAULT 0,
    completed_days INTEGER NOT NULL DEFAULT 0,
    break_count INTEGER NOT NULL DEFAULT 0,
    last_completed_day TEXT,
    owner_sent_day TEXT,
    peer_sent_day TEXT,
    last_pose TEXT,
    last_success_message_id INTEGER,
    last_warning_day TEXT,
    last_broken_day TEXT,
    notifications_enabled INTEGER NOT NULL DEFAULT 1,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    freeze_count INTEGER NOT NULL DEFAULT 3,
    auto_freeze INTEGER NOT NULL DEFAULT 0,
    freezes_used INTEGER NOT NULL DEFAULT 0,
    revivable_streak INTEGER NOT NULL DEFAULT 0,
    revivable_day TEXT,
    freeze_seed_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS streak_activations (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    activated_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processed_messages (
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (business_connection_id, chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS sticker_cache (
    sticker_key TEXT PRIMARY KEY,
    telegram_file_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS freeze_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    protected_day TEXT NOT NULL,
    used_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS guest_streak_requests (
    token TEXT PRIMARY KEY,
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    summon_message_id INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS streak_revive_requests (
    token TEXT PRIMARY KEY,
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    owner_user_id INTEGER NOT NULL,
    peer_user_id INTEGER NOT NULL,
    owner_approved INTEGER NOT NULL DEFAULT 0,
    peer_approved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS streak_start_requests (
    token TEXT PRIMARY KEY,
    business_connection_id TEXT NOT NULL,
    chat_id INTEGER NOT NULL,
    peer_user_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE (business_connection_id, chat_id),
    FOREIGN KEY (business_connection_id)
        REFERENCES business_connections(business_connection_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_guest_streak_requests_expiry
ON guest_streak_requests(expires_at);

CREATE INDEX IF NOT EXISTS idx_streak_revive_requests_expiry
ON streak_revive_requests(expires_at);

CREATE INDEX IF NOT EXISTS idx_streak_start_requests_expiry
ON streak_start_requests(expires_at);

CREATE INDEX IF NOT EXISTS idx_streaks_peer
ON streaks(peer_user_id);

CREATE INDEX IF NOT EXISTS idx_streaks_connection
ON streaks(business_connection_id);

CREATE INDEX IF NOT EXISTS idx_streaks_chat
ON streaks(chat_id);

CREATE INDEX IF NOT EXISTS idx_streaks_last_completed
ON streaks(last_completed_day);

CREATE INDEX IF NOT EXISTS idx_processed_messages_time
ON processed_messages(processed_at);
