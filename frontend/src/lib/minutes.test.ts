import { describe, expect, it } from "vitest"
import { ownerOrg, parseMinutes, toMarkdown, type Minutes } from "./minutes"

const SAMPLE = `# محضر اجتماع — اجتماع المتابعة (2026-06-01)

| التاريخ | الوقت | الموقع |
| --- | --- | --- |
| 2026-06-01 | 10:00 ص | عن بُعد |

## قائمة الحضور
| # | الاسم | الجهة |
| --- | --- | --- |
| 1 | مشاري العتيبي |  |
| 2 | نورة القحطاني | هيئة الاتصالات وتقنية المعلومات |

## نقاط نقاش الاجتماع
**ملخص الاجتماع**
استُعرضت خطة الربع الثالث وميزانيتها.

- نوقشت بنود الميزانية التشغيلية.

## نتائج الاجتماع
| المهام/ التوصيات | المسؤول | التاريخ المستهدف |
| --- | --- | --- |
| تعديل ملف الإكسل | مشاري العتيبي | — |
| إعداد عرض الأجندة | نورة القحطاني | 2026-06-10 |`

describe("parseMinutes", () => {
  it("extracts the title, date, time, and location from the header", () => {
    const m = parseMinutes(SAMPLE)
    expect(m.title).toBe("اجتماع المتابعة")
    expect(m.date).toBe("2026-06-01")
    expect(m.time).toBe("10:00 ص")
    expect(m.location).toBe("عن بُعد")
  })

  it("extracts attendees, leaving an unknown الجهة empty", () => {
    const m = parseMinutes(SAMPLE)
    expect(m.attendees).toEqual([
      { name: "مشاري العتيبي", org: "" },
      { name: "نورة القحطاني", org: "هيئة الاتصالات وتقنية المعلومات" },
    ])
  })

  it("separates the summary paragraph from the bulleted points", () => {
    const m = parseMinutes(SAMPLE)
    expect(m.summary).toBe("استُعرضت خطة الربع الثالث وميزانيتها.")
    expect(m.points).toEqual(["نوقشت بنود الميزانية التشغيلية."])
  })

  it("keeps the assignee's name in outcomes (the app maps it to an org for display)", () => {
    const m = parseMinutes(SAMPLE)
    expect(m.outcomes).toEqual([
      { task: "تعديل ملف الإكسل", person: "مشاري العتيبي", date: "" },
      { task: "إعداد عرض الأجندة", person: "نورة القحطاني", date: "2026-06-10" },
    ])
  })

  it("drops placeholder «» and dash cells", () => {
    const md = `## قائمة الحضور
| # | الاسم | الجهة |
| --- | --- | --- |
| 1 | «اسم الحاضر» | «الجهة» |
| 2 | مشاري | — |`
    expect(parseMinutes(md).attendees).toEqual([{ name: "مشاري", org: "" }])
  })
})

describe("ownerOrg", () => {
  const base: Minutes = {
    title: "",
    date: "",
    time: "",
    location: "",
    attendees: [
      { name: "مشاري العتيبي", org: "وزارة المالية" },
      { name: "نورة القحطاني", org: "" },
    ],
    summary: "",
    points: [],
    outcomes: [],
  }

  it("returns the assignee's organization", () => {
    expect(ownerOrg(base, "مشاري العتيبي")).toBe("وزارة المالية")
  })

  it("returns — when the organization is not filled in", () => {
    expect(ownerOrg(base, "نورة القحطاني")).toBe("—")
  })

  it("returns — when the person is not in the roster", () => {
    expect(ownerOrg(base, "زائر")).toBe("—")
  })

  it("matches names ignoring surrounding whitespace", () => {
    expect(ownerOrg(base, "  مشاري العتيبي  ")).toBe("وزارة المالية")
  })
})

describe("toMarkdown", () => {
  it("renders the owner column as the assignee's organization, not their name", () => {
    const md = toMarkdown(parseMinutes(SAMPLE))
    // نورة's task → her organization; مشاري (no org yet) → a dash.
    expect(md).toContain("| إعداد عرض الأجندة | هيئة الاتصالات وتقنية المعلومات | 2026-06-10 |")
    // مشاري's task owner is a dash (his name is never the owner), not "مشاري العتيبي".
    expect(md).toContain("| تعديل ملف الإكسل | — | — |")
  })

  it("round-trips the meta, attendees, and discussion through markdown", () => {
    const m1 = parseMinutes(SAMPLE)
    const m2 = parseMinutes(toMarkdown(m1))
    expect(m2.title).toBe(m1.title)
    expect(m2.date).toBe(m1.date)
    expect(m2.time).toBe(m1.time)
    expect(m2.location).toBe(m1.location)
    expect(m2.attendees).toEqual(m1.attendees)
    expect(m2.summary).toBe(m1.summary)
    expect(m2.points).toEqual(m1.points)
  })
})
