import { describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { MinutesPane } from "./MinutesPane"

const SAMPLE = `# Weekly Sync — 2026-06-01

## Q3 Budget
Infra is 12% over.

## Decisions & Action Items
- **Action:** Bob — numbers (Friday)`

describe("MinutesPane", () => {
  it("shows the empty state before generation", () => {
    render(<MinutesPane state="input" minutes="" title="" />)
    expect(screen.getByText(/Your minutes appear here/i)).toBeInTheDocument()
  })

  it("shows a staged status while loading", () => {
    render(<MinutesPane state="loading" minutes="" title="" />)
    expect(screen.getByText(/Reading the transcript/i)).toBeInTheDocument()
  })

  it("renders the markdown headings in the result state", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="Weekly Sync" />)
    expect(screen.getByRole("heading", { level: 1, name: /Weekly Sync/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 2, name: /Q3 Budget/i })).toBeInTheDocument()
    expect(screen.getByRole("heading", { level: 2, name: /Decisions & Action Items/i })).toBeInTheDocument()
  })

  it("exposes copy, download, and print actions in the result state", () => {
    render(<MinutesPane state="result" minutes={SAMPLE} title="Weekly Sync" />)
    expect(screen.getByRole("button", { name: /copy/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /print/i })).toBeInTheDocument()
  })

  it("edits inline in the rendered document and exports markdown", () => {
    const onChange = vi.fn()
    render(<MinutesPane state="result" minutes={SAMPLE} title="x" onChange={onChange} />)
    fireEvent.click(screen.getByRole("button", { name: /edit/i }))

    const doc = screen.getByLabelText(/edit minutes/i)
    expect(doc).toHaveAttribute("contenteditable", "true")

    doc.innerHTML = "<h2>عنوان جديد</h2><p>نص</p>"
    fireEvent.input(doc)

    expect(onChange).toHaveBeenCalled()
    const lastArg = onChange.mock.calls.at(-1)?.[0] as string
    expect(lastArg).toContain("عنوان جديد")
  })
})
