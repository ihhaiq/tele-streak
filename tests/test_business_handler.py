from app.handlers.business import is_start_streak_query, is_streak_query


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


def test_start_streak_query_accepts_owner_phrases():
    assert is_start_streak_query("بدأ ستريك")
    assert is_start_streak_query("بدا ستريك")
    assert is_start_streak_query("ابدأ ستريك")
    assert is_start_streak_query("بـدأ سـتريك")
    assert is_start_streak_query("start streak")


def test_start_streak_query_rejects_unrelated_text():
    assert not is_start_streak_query("ستريك")
    assert not is_start_streak_query("بدأ")
    assert not is_start_streak_query("خل نبدأ ستريك")
