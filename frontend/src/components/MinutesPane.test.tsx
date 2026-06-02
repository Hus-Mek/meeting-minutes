import { describe, expect, it } from "vitest"
import { fireEvent, render, screen, within } from "@testing-library/react"
import { MinutesPane } from "./MinutesPane"

// A small but realistic محضر اجتماع. مشاري has no الجهة yet; نورة's is known.
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

// The نتائج table, scoped via its unique "المسؤول" header (other tables have no such column).
function outcomesTable() {
  return within(screen.getByRole("columnheader", { name: "المسؤول" }).closest("table")!)
}

describe("MinutesPane", () => {
  it("shows the empty state before generation", () => {
    render(<MinutesPane state="input" minutes="" title="" />)
    expect(screen.getByText(/Your minutes appear here/i)).toBeInTheDocument()
  })

  it("shows a staged status while loading", () => {
    render(<MinutesPane state="loading" minutes="" title="" />)
    expect(screen.getByText(/Reading the transcript/i)).toBeInTheDocument()
  })

  it("renders the formal محضر اجتماع section headings in the result state", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="اجتماع المتابعة" />)
    expect(screen.getByRole("heading", { name: "قائمة الحضور" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "نقاط نقاش الاجتماع" })).toBeInTheDocument()
    expect(screen.getByRole("heading", { name: "نتائج الاجتماع" })).toBeInTheDocument()
  })

  it("exposes edit, copy, .md, and PDF actions in the result state", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="x" />)
    expect(screen.getByRole("button", { name: /edit/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /\.md/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /pdf/i })).toBeInTheDocument()
  })

  it("shows the assignee's organization in المسؤول, not their name", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="x" />)
    // نورة's known الجهة surfaces as the owner of her task…
    expect(outcomesTable().getByText("هيئة الاتصالات وتقنية المعلومات")).toBeInTheDocument()
    // …while مشاري (no الجهة yet) shows the placeholder dash, never his name.
    expect(outcomesTable().queryByText("مشاري العتيبي")).not.toBeInTheDocument()
  })

  it("updates the المسؤول column live when an attendee's الجهة is filled in", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="x" />)
    fireEvent.click(screen.getByRole("button", { name: /edit/i }))

    // Two الجهة inputs (one per attendee); the first is مشاري's (the assignee).
    const orgInputs = screen.getAllByPlaceholderText("أدخل الجهة")
    fireEvent.change(orgInputs[0], { target: { value: "وزارة المالية" } })

    // The owner of مشاري's task reflects the new organization reactively.
    expect(outcomesTable().getByText("وزارة المالية")).toBeInTheDocument()
  })
})
