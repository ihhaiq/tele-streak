from app.handlers.guest import extract_streak_guest_request


def test_guest_parser_accepts_broken_notice_and_broken_events():
    assert extract_streak_guest_request(
        "@HStreakBot streak:broken_notice:AbCd_123"
    ) == ("broken_notice", "AbCd_123")
    assert extract_streak_guest_request(
        "@HStreakBot streak:broken:EfGh_456"
    ) == ("broken", "EfGh_456")
