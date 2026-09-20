import hashlib
import hmac
import json
from urllib.parse import urlencode

from app.story.web import StoryShareSigner, validate_telegram_init_data


def make_init_data(bot_token: str, user_id: int, auth_date: int) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "AAEAAAE",
        "user": json.dumps(
            {"id": user_id, "first_name": "A"},
            separators=(",", ":"),
        ),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, data_check.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(values)


def test_story_share_token_is_short_signed_and_expires():
    signer = StoryShareSigner("123456:secret", ttl_seconds=600)
    token = signer.issue(1234567890, -1001234567890, "video10", now=1_000)

    assert len(token) <= 64
    decoded = signer.parse(token, now=1_599)
    assert decoded is not None
    assert decoded.owner_id == 1234567890
    assert decoded.chat_id == -1001234567890
    assert decoded.kind == "video10"
    assert signer.parse(token, now=1_601) is None

    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert signer.parse(changed, now=1_100) is None


def test_telegram_init_data_validation_accepts_owner_and_rejects_tampering():
    bot_token = "123456:secret"
    payload = make_init_data(bot_token, 77, 10_000)
    assert validate_telegram_init_data(
        payload, bot_token, max_age_seconds=600, now=10_100
    ) == 77

    tampered = payload.replace("%22id%22%3A77", "%22id%22%3A78")
    assert (
        validate_telegram_init_data(
            tampered, bot_token, max_age_seconds=600, now=10_100
        )
        is None
    )
    assert (
        validate_telegram_init_data(
            payload, bot_token, max_age_seconds=60, now=10_100
        )
        is None
    )
