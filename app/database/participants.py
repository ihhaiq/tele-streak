from __future__ import annotations

import json


def account_name(user) -> str | None:
    name = getattr(user, "full_name", None)
    username = getattr(user, "username", None)
    return clean_name(name) or (f"@{username}" if isinstance(username, str) and username else None)


def clean_name(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    return name.strip()[:256] or None


async def save_account(db, user_id: int, name: str | None) -> None:
    await db.execute(
        """INSERT INTO participant_accounts(user_id, display_name) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        display_name=excluded.display_name
        WHERE excluded.display_name IS NOT NULL
          AND excluded.display_name IS NOT participant_accounts.display_name""",
        (user_id, clean_name(name)),
    )


async def participant_names(db, connection_id: str, chat_id: int) -> tuple[str | None, str | None]:
    row = await (await db.execute(
        """SELECT owner.display_name AS owner_name, peer.display_name AS peer_name,
                  p.state AS profile
        FROM business_connections b
        LEFT JOIN streaks s ON s.business_connection_id=b.business_connection_id AND s.chat_id=?
        LEFT JOIN participant_accounts owner ON owner.user_id=b.owner_user_id
        LEFT JOIN participant_accounts peer ON peer.user_id=COALESCE(s.peer_user_id, ?)
        LEFT JOIN adventure_profiles p ON p.business_connection_id=b.business_connection_id AND p.chat_id=?
        WHERE b.business_connection_id=?""",
        (chat_id, chat_id, chat_id, connection_id),
    )).fetchone()
    if row is None:
        return None, None
    # أسماء السجلات القديمة تبقى متاحة قبل وصول رسالة جديدة.
    stats = json.loads(row["profile"]).get("stats", {}) if row["profile"] else {}
    return tuple(
        clean_name(row[f"{role}_name"]) or clean_name(stats.get(role, {}).get("name"))
        for role in ("owner", "peer")
    )
