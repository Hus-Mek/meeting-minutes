import type { Minutes } from "@/lib/minutes"
import { ownerOrg } from "@/lib/minutes"

// Renders the minutes in the formal محضر اجتماع layout (mirrors the .docx). When
// `editable`, fields are inputs/textareas styled to blend into the document, so
// editing keeps the same view and the assignee→organization owner updates live.
// The same component renders to static HTML for PDF export (editable=false).

interface TemplateProps {
  minutes: Minutes
  editable?: boolean
  onChange?: (next: Minutes) => void
}

export function DefaultTemplate({ minutes: m, editable = false, onChange }: TemplateProps) {
  const set = (patch: Partial<Minutes>) => onChange?.({ ...m, ...patch })
  const setAttendee = (i: number, patch: Partial<Minutes["attendees"][number]>) =>
    set({ attendees: m.attendees.map((a, idx) => (idx === i ? { ...a, ...patch } : a)) })
  const setOutcome = (i: number, patch: Partial<Minutes["outcomes"][number]>) =>
    set({ outcomes: m.outcomes.map((o, idx) => (idx === i ? { ...o, ...patch } : o)) })

  return (
    <div dir="rtl" className="tmpl-default minutes-doc mx-auto">
      <table className="mm-hdr">
        <tbody>
          <tr>
            <th className="mm-title" colSpan={3}>
              محضر اجتماع — <Field v={m.title} edit={editable} on={(v) => set({ title: v })} ph="العنوان" inline />
            </th>
          </tr>
          <tr>
            <th>التاريخ</th>
            <th>الوقت</th>
            <th>الموقع</th>
          </tr>
          <tr>
            <td><Field v={m.date} edit={editable} on={(v) => set({ date: v })} /></td>
            <td><Field v={m.time} edit={editable} on={(v) => set({ time: v })} /></td>
            <td><Field v={m.location} edit={editable} on={(v) => set({ location: v })} /></td>
          </tr>
        </tbody>
      </table>

      <h2>قائمة الحضور</h2>
      <table>
        <thead>
          <tr>
            <th className="mm-num">#</th>
            <th>الاسم</th>
            <th>الجهة</th>
          </tr>
        </thead>
        <tbody>
          {m.attendees.map((a, i) => (
            <tr key={i}>
              <td className="mm-num">{i + 1}</td>
              <td><Field v={a.name} edit={editable} on={(v) => setAttendee(i, { name: v })} /></td>
              <td>
                <Field
                  v={a.org}
                  edit={editable}
                  on={(v) => setAttendee(i, { org: v })}
                  ph="أدخل الجهة"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>نقاط نقاش الاجتماع</h2>
      <table className="mm-discussion">
        <thead>
          <tr>
            <th>ملخص الاجتماع</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              {editable ? (
                <>
                  <textarea
                    className="mm-edit mm-area"
                    rows={2}
                    value={m.summary}
                    placeholder="فقرة تمهيدية"
                    onChange={(e) => set({ summary: e.target.value })}
                  />
                  <textarea
                    className="mm-edit mm-area"
                    rows={Math.max(3, m.points.length)}
                    value={m.points.join("\n")}
                    placeholder="نقطة لكل سطر"
                    onChange={(e) => set({ points: e.target.value.split("\n") })}
                  />
                </>
              ) : (
                <>
                  {m.summary && <p>{m.summary}</p>}
                  <ul>
                    {m.points.filter((p) => p.trim()).map((p, i) => (
                      <li key={i}>{p}</li>
                    ))}
                  </ul>
                </>
              )}
            </td>
          </tr>
        </tbody>
      </table>

      <h2>نتائج الاجتماع</h2>
      <table>
        <thead>
          <tr>
            <th>المهام/ التوصيات</th>
            <th>المسؤول</th>
            <th>التاريخ المستهدف</th>
          </tr>
        </thead>
        <tbody>
          {m.outcomes.map((o, i) => (
            <tr key={i}>
              <td><Field v={o.task} edit={editable} on={(v) => setOutcome(i, { task: v })} /></td>
              <td className="mm-owner">{ownerOrg(m, o.person)}</td>
              <td><Field v={o.date} edit={editable} on={(v) => setOutcome(i, { date: v })} ph="—" /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface FieldProps {
  v: string
  edit: boolean
  on: (value: string) => void
  ph?: string
  inline?: boolean
}

function Field({ v, edit, on, ph, inline }: FieldProps) {
  if (!edit) return <>{v || "—"}</>
  return (
    <input
      className={inline ? "mm-edit mm-inline" : "mm-edit"}
      value={v}
      placeholder={ph}
      onChange={(e) => on(e.target.value)}
    />
  )
}
