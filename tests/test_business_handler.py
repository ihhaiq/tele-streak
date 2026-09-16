from app.handlers.business import is_streak_query


def test_streak_query_accepts_arabic_variants():
    assert is_streak_query("ستريك")
    assert is_streak_query("  سـتريك  ")
    assert is_streak_query("/ستريك")
    assert is_streak_query("ستريك 🔥")


def test_streak_query_accepts_english_command():
    assert is_streak_query("streak")
    assert is_streak_query("/streak@HStreakBot")


def test_streak_query_does_not_consume_normal_message():
    assert not is_streak_query("شلونك")
    assert not is_streak_query(None)
