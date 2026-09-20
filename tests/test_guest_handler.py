from app.handlers.guest import extract_streak_guest_request


def test_guest_event_parser_accepts_supported_events():
    token = "AbCd_123"
    for event in (
        "status",
        "success",
        "warning_sticker",
        "warning_notice",
        "broken",
        "revive",
    ):
        assert extract_streak_guest_request(
            f"@HStreakBot streak:{event}:{token}"
        ) == (event, token)


def test_guest_event_parser_rejects_unknown_or_short_tokens():
    assert extract_streak_guest_request("@HStreakBot streak:unknown:AbCd_123") is None
    assert extract_streak_guest_request("@HStreakBot streak:revive:short") is None
    assert extract_streak_guest_request(None) is None

