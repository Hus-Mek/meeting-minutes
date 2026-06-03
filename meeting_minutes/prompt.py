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
# Placeholders shown between «» are illustrative ONLY and must never appear in output.
_CONTRACT = """\
اكتب محضر الاجتماع بالعربية الفصحى الرسمية، بصيغة Markdown (GitHub-Flavored)، وبهذه البنية والعناوين حرفيًا. النصوص الموضوعة بين «» هي أمثلة توضيحية فقط، استبدلها بالمحتوى الفعلي ولا تُبقِ أي علامات «» أو نص توضيحي في المخرجات:

# محضر اجتماع — {heading}

| التاريخ | الوقت | الموقع |
| --- | --- | --- |
| {date} | {time} | {location} |

## قائمة الحضور
| # | الاسم | الجهة |
| --- | --- | --- |
| 1 | «اسم الحاضر» | «الجهة» |

## نقاط نقاش الاجتماع
**ملخص الاجتماع**
«فقرة تمهيدية من جملة أو جملتين تذكر ما استُعرض ومن قدّمه»

- «نقطة نقاش مفصّلة»
- «نقطة نقاش مفصّلة»

## نتائج الاجتماع
| المهام/ التوصيات | المسؤول | التاريخ المستهدف |
| --- | --- | --- |
| «المهمة أو التوصية» | «الاسم الكامل للشخص المكلّف» | «التاريخ أو —» |

قواعد الإخراج:
- التزم بالعناوين الأربعة أعلاه وبهذا الترتيب تمامًا، ولا تضف أقسامًا أخرى، ولا تكتب أي نص توضيحي أو placeholder (مثل «...» أو «نقطة نقاش») في المخرجات.
- قائمة الحضور: استخرج المتحدثين الحقيقيين من النص (تجاهل "Unidentified Speaker")، وادمجهم مع قائمة الحضور المزوّدة لتحديد الجهة؛ واترك خانة الجهة فارغة (—) إن كانت غير معروفة. استخدم **نفس صيغة الاسم بالضبط** في جدولي «قائمة الحضور» و«نتائج الاجتماع».
- اكتب جميع **أسماء الأشخاص بالعربية** أينما وردت (في «قائمة الحضور» و«المسؤول» وداخل نقاط النقاش). إذا ورد الاسم في النص باللاتينية (مثل أسماء Teams) فاكتبه **بالحروف العربية وفق النطق السعودي المتعارف عليه** ولا تُبقِ أي اسم لاتينيًا، مع الحفاظ على نفس الصيغة العربية بالضبط في كل المواضع (مثال: Meshari Alzanbaqi ← مشاري الزنباقي). وعرّب حرف **g** الإنجليزي (الجيم الصلبة) بحرف **القاف (ق)** وفق النطق السعودي، لا بالجيم (ج) ولا الغين (غ) (مثال: Algahtani ← القحطاني، Gosaibi ← القصيبي، Gassim ← القصيم). هذا لا يشمل المصطلحات التقنية الإنجليزية التي تبقى كما هي.
- نقاط النقاش يجب أن تكون **تفصيلية وشاملة**: لكل موضوع نوقش اكتب نقطة وافية (جملة أو عدة جمل) تشرح ما دار والتفاصيل المهمة (الأرقام، المدد، القرارات، المبررات، نقاط الاتفاق والخلاف). اعتمد على «Key Discussion Points» في مسودة read.ai إن وُجدت وعلى النص الحرفي، **ولا تكتفِ بنسخ قائمة «Summary» المختصرة**. رتّب النقاط حسب الأهمية، واكتب نقاطًا كثيرة بقدر ما يحتمله النقاش الفعلي.
- نتائج الاجتماع: أدرج المهام والتوصيات (يمكنك دمج المتقاربة جدًا). في عمود «المسؤول» اكتب **الاسم الكامل للشخص المكلّف بالمهمة** بنفس صيغة اسمه في قائمة الحضور تمامًا (سيتولّى النظام لاحقًا استبدال الاسم بجهته). اترك «التاريخ المستهدف» فارغًا (—) إن لم يُذكر.
- **التزم بالتطابق الصرفي الصحيح للجنس**، وصُغ المهام والتوصيات بصيغة اسمية محايدة (مثل: «تعديل ملف الإكسل»، «إدراج شريحة أجندة») وتجنّب صيغ الأمر المُجنّسة (عدّل/عدّلي، قدّم/قدّمي).
- لا تختلق قرارات أو أسماء أو أرقامًا أو تواريخ. أبقِ المصطلحات التقنية الإنجليزية (Workflow, API) كما وردت عند اللزوم.
- إذا وردت شرطة عمودية (|) داخل نص خلية في أي جدول، فاكتبها مهرّبة هكذا \\| حتى لا تكسر بنية الجدول.
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
# IMPORTANT: the owner must be the assignee's PERSON NAME (same spelling as the
# transcript/roster), NOT their organization — the app maps the name to the الجهة
# downstream, and the synthesis step only sees these summaries, so emitting an org
# here would put an org in the «المسؤول» column and break that lookup.
WINDOW_SYSTEM_PROMPT = """\
أنت كاتب محضر تلخّص مقطعًا واحدًا من نص اجتماع أطول. استخرج **بتفصيل** وبنقاط Markdown:
- جميع نقاط النقاش والقرارات والملاحظات، مع التفاصيل المهمة (الأرقام، المدد، المبررات، نقاط الاتفاق/الخلاف).
- المهام والتوصيات، مع **اسم الشخص المكلّف كاملًا** كما ورد في النص (لا الجهة) والتاريخ المستهدف إن وُجد.
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
