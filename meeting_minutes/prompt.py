"""Prompt construction for formal Arabic meeting minutes (محضر اجتماع).

Output structure (fixed), modelled on the user's real template:
- a header table: التاريخ | الوقت | الموقع
- ## قائمة الحضور — table of الاسم | الجهة
- ## نقاط نقاش الاجتماع — ملخص الاجتماع + bulleted discussion points
- ## نتائج الاجتماع — table of المهام/التوصيات | المسؤول | التاريخ المستهدف

Strategy unchanged: the human **notes are the spine** (priority/emphasis); the
**transcript is ground truth** for facts. Attendees are hybrid — names come from
the transcript, organizations from the provided roster.
"""

from __future__ import annotations


def _cell(value: str) -> str:
    return value.strip() if value and value.strip() else "—"


_GROUNDING_TRANSCRIPT = (
    "- اعتمد على النص الحرفي (TRANSCRIPT) كمصدر للحقائق: الأسماء والأرقام والقرارات ومن قال ماذا.\n"
    "- الملاحظات (NOTES) تحدّد الأولوية والتركيز فقط، لا تخترع منها وقائع."
)
_GROUNDING_SUMMARIES = (
    "- اعتمد على ملخصات المقاطع (SUMMARIES) المعطاة كمصدر للحقائق (لا ترى النص الكامل).\n"
    "- الملاحظات (NOTES) تحدّد الأولوية والتركيز فقط."
)

# The fixed Arabic document contract. {heading}/{date}/{time}/{location} are literal.
_CONTRACT = """\
اكتب محضر الاجتماع بالعربية الفصحى الرسمية، بصيغة Markdown (GitHub-Flavored)، وبهذه البنية والعناوين حرفيًا:

# محضر اجتماع — {heading}

| التاريخ | الوقت | الموقع |
| --- | --- | --- |
| {date} | {time} | {location} |

## قائمة الحضور
| # | الاسم | الجهة |
| --- | --- | --- |
| 1 | … | … |

## نقاط نقاش الاجتماع
**ملخص الاجتماع**
فقرة تمهيدية تذكر ما استُعرض ومن قدّمه، ثم قائمة نقاط تفصيلية:
- نقطة نقاش تفصيلية
- نقطة نقاش تفصيلية

## نتائج الاجتماع
| المهام/ التوصيات | المسؤول | التاريخ المستهدف |
| --- | --- | --- |
| … | … | … |

قواعد الإخراج:
- التزم بالعناوين الأربعة أعلاه وبهذا الترتيب تمامًا، ولا تضف أقسامًا أخرى.
- قائمة الحضور: استخرج المتحدثين الحقيقيين من النص (تجاهل "Unidentified Speaker")، وادمجهم مع قائمة الحضور المزوّدة لتحديد الجهة؛ واترك خانة الجهة فارغة (—) إن كانت غير معروفة.
- نقاط النقاش يجب أن تكون **تفصيلية وشاملة**: غطِّ كل موضوع ومهمة ومرحلة نوقشت، واذكر التفاصيل المهمة لكل بند (الأرقام، المدد الزمنية، القرارات، المبررات، نقاط الاتفاق والخلاف، والملاحظات على كل عنصر). لا تختصر بإفراط — اكتب نقطة منفصلة لكل فكرة جوهرية، ورتّب النقاط حسب الأهمية كما تشير الملاحظات. اكتب نقاطًا كثيرة بقدر ما يحتمله النقاش الفعلي.
- نتائج الاجتماع: صفّ لكل مهمة أو توصية. **عمود «المسؤول» يجب أن يكون الجهة أو الشركة المسؤولة** (مثل: «شركة هوّز»، «الإدارة العامة للتراخيص») **وليس اسم شخص**؛ إن نُسبت المهمة إلى شخص فاذكر جهته بدلًا منه (استعن بقائمة الحضور لمعرفة الجهة). اترك التاريخ المستهدف فارغًا (—) إن لم يُذكر.
- لا تختلق قرارات أو أسماء أو أرقامًا أو تواريخ. أبقِ المصطلحات التقنية الإنجليزية (Workflow, API) كما وردت عند اللزوم.
- أخرج وثيقة Markdown فقط، دون أي نص إضافي قبلها أو بعدها."""

# Optional read.ai recap: a weak, possibly-inaccurate AI draft — a hint only.
_RECAP_NOTE = (
    "- قد تُعطى أيضًا مسودة تلخيص آلية (recap) من read.ai، وهي **ناقصة وقد تكون غير دقيقة**: "
    "استأنس بها فقط للبنية واكتشاف المهام/البنود التي قد تخفى، ولا تعتمدها مصدرًا للحقائق "
    "أبدًا — النص الحرفي/الملخصات هو المرجع."
)

_SYSTEM = """\
أنت كاتب محاضر اجتماعات محترف ودقيق للاجتماعات الرسمية الحكومية والمؤسسية.
{source_desc}

طريقة استخدام المصادر:
{grounding}
{recap_note}

{contract}"""

# Map step: summarise one transcript window in DETAIL so the merged minutes stay rich.
WINDOW_SYSTEM_PROMPT = """\
أنت كاتب محضر تلخّص مقطعًا واحدًا من نص اجتماع أطول. استخرج **بتفصيل** وبنقاط Markdown:
- جميع نقاط النقاش والقرارات والملاحظات، مع التفاصيل المهمة (الأرقام، المدد، المبررات، نقاط الاتفاق/الخلاف).
- المهام والتوصيات، مع **الجهة/الشركة المسؤولة** (لا اسم شخص) والتاريخ المستهدف إن وُجد.
- أسماء المتحدثين وجهاتهم إن ذُكرت، مع الحفاظ على المصطلحات والأرقام كما هي.
لا تختصر بإفراط ولا تختلق شيئًا. أخرج النقاط فقط."""

_USER = """\
<roster>
{attendees}
</roster>

<notes>
{notes}
</notes>

<recap_readai_unreliable>
{recap}
</recap_readai_unreliable>

<transcript>
{transcript}
</transcript>

اكتب محضر الاجتماع الآن وفق البنية المطلوبة."""

_WINDOW_USER = """\
<priority_notes>
{notes}
</priority_notes>

<transcript_segment>
{transcript}
</transcript_segment>

لخّص هذا المقطع الآن مع الحفاظ على التفاصيل المتعلقة بالأولويات أعلاه."""

_SYNTHESIS_USER = """\
<roster>
{attendees}
</roster>

<notes>
{notes}
</notes>

<recap_readai_unreliable>
{recap}
</recap_readai_unreliable>

<segment_summaries>
{summaries}
</segment_summaries>

ادمج ملخصات المقاطع في محضر اجتماع نهائي وفق البنية المطلوبة، مع إزالة التكرار."""


def _build_heading(title: str, date: str) -> str:
    title = title.strip() or "اجتماع"
    return f"{title} ({date.strip()})" if date.strip() else title


def build_system_prompt(
    *,
    title: str,
    date: str,
    time: str = "",
    location: str = "",
    for_synthesis: bool = False,
) -> str:
    """System prompt for the single-pass call or the synthesis (reduce) call."""
    contract = _CONTRACT.format(
        heading=_build_heading(title, date),
        date=_cell(date),
        time=_cell(time),
        location=_cell(location),
    )
    if for_synthesis:
        source_desc = "تُعطى لك ملخصات مقاطع الاجتماع وملاحظات أحد المشاركين."
        grounding = _GROUNDING_SUMMARIES
    else:
        source_desc = "تُعطى لك نص الاجتماع الحرفي وملاحظات أحد المشاركين."
        grounding = _GROUNDING_TRANSCRIPT
    return _SYSTEM.format(
        source_desc=source_desc, grounding=grounding, recap_note=_RECAP_NOTE, contract=contract
    )


def build_user_prompt(
    *, notes: str, transcript: str, attendees: str = "", recap: str = ""
) -> str:
    """User prompt pairing the roster + notes (spine) + optional recap with the transcript."""
    return _USER.format(
        attendees=_cell(attendees),
        notes=_cell(notes),
        recap=_cell(recap),
        transcript=transcript.strip(),
    )


def build_window_user(*, notes: str, transcript: str) -> str:
    """User prompt for the map step: a window plus the notes as a priority hint."""
    return _WINDOW_USER.format(notes=_cell(notes), transcript=transcript.strip())


def build_synthesis_prompt(
    *, notes: str, summaries: str, attendees: str = "", recap: str = ""
) -> str:
    """User prompt that merges per-window summaries (map-reduce reduce step)."""
    return _SYNTHESIS_USER.format(
        attendees=_cell(attendees),
        notes=_cell(notes),
        recap=_cell(recap),
        summaries=summaries.strip(),
    )
