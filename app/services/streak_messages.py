from aiogram.types import (
    InputRichBlockDivider,
    InputRichBlockParagraph,
    InputRichBlockSectionHeading,
    InputRichMessage,
)

BROKEN_NOTICE_TITLE = "الستريك مات ونحن من قتلناه"
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


def build_broken_notice_rich_message() -> InputRichMessage:
    return InputRichMessage(
        blocks=[
            InputRichBlockSectionHeading(text=BROKEN_NOTICE_TITLE, size=1),
            InputRichBlockDivider(),
            *(
                InputRichBlockParagraph(text=paragraph)
                for paragraph in BROKEN_NOTICE_PARAGRAPHS
            ),
        ],
        is_rtl=True,
    )
