from aiogram.types import (
    InputMediaAnimation,
    InputRichBlockAnimation,
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichMessage,
)

BROKEN_NOTICE_TITLE = "💔 الستريك مات"
BROKEN_NOTICE_PARAGRAPHS = (
    "ما كملتوا شرط اليوم، ولهذا انقطع الستريك.",
    (
        "إذا تريدون ترجعوه، واحد منكم يكتب «احياء الستريك» هنا. "
        "راح يطلع طلب إحياء، وبعدها لازم الطرفين يضغطون ✅ موافقة."
    ),
    (
        "إذا وافق طرف واحد بس، ما يرجع الستريك. وإذا وافقتوا اثنينكم، "
        "يستخدم البوت 🧊 من رصيد الحماية ويرجع الستريك مثل ما كان."
    ),
)

BROKEN_NOTICE_TEXT = (
    BROKEN_NOTICE_TITLE
    + "\n\n"
    + "\n\n".join(BROKEN_NOTICE_PARAGRAPHS)
)


def build_broken_notice_rich_message(animation_file_id: str | None) -> InputRichMessage:
    blocks = [
        InputRichBlockSectionHeading(text=BROKEN_NOTICE_TITLE, size=1),
        InputRichBlockDivider(),
    ]
    if animation_file_id:
        blocks.append(
            InputRichBlockAnimation(
                animation=InputMediaAnimation(media=animation_file_id),
            )
        )
    blocks.extend(
        InputRichBlockParagraph(text=paragraph)
        for paragraph in BROKEN_NOTICE_PARAGRAPHS
    )
    return InputRichMessage(blocks=blocks, is_rtl=True)
