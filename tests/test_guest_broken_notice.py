from app.handlers.guest_broken_notice import BROKEN_NOTICE_RE
from app.services.streak_messages import BROKEN_NOTICE_TEXT


def test_broken_notice_event_parser_accepts_guest_token():
    match = BROKEN_NOTICE_RE.search("@HStreakBot streak:broken_notice:AbCd_123")
    assert match is not None
    assert match.group(1) == "AbCd_123"


def test_broken_notice_explains_two_party_revival():
    assert "احياء الستريك" in BROKEN_NOTICE_TEXT
    assert "الطرفين" in BROKEN_NOTICE_TEXT
    assert "✅ موافقة" in BROKEN_NOTICE_TEXT
    assert "🧊" in BROKEN_NOTICE_TEXT
