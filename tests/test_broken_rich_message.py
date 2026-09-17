from app.services.streak_messages import (
    BROKEN_NOTICE_PARAGRAPHS,
    BROKEN_NOTICE_TITLE,
    build_broken_notice_rich_message,
)


def test_broken_rich_message_is_text_only_with_requested_title():
    rich = build_broken_notice_rich_message()

    assert rich.is_rtl is True
    assert rich.blocks is not None
    assert rich.blocks[0].__class__.__name__ == "InputRichBlockSectionHeading"
    assert rich.blocks[0].size == 1
    assert rich.blocks[0].text == "الستريك مات ونحن من قتلناه"
    assert BROKEN_NOTICE_TITLE == "الستريك مات ونحن من قتلناه"
    assert rich.blocks[1].__class__.__name__ == "InputRichBlockDivider"
    assert all(
        block.__class__.__name__ != "InputRichBlockAnimation"
        for block in rich.blocks
    )
    assert [
        block.text
        for block in rich.blocks[2:]
    ] == list(BROKEN_NOTICE_PARAGRAPHS)
