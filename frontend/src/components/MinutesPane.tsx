import { useEffect, useState } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { Check, Copy, Download, Eye, FileDown, FileText, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { DefaultTemplate } from "@/components/templates/DefaultTemplate"
import { buildStandaloneHtml } from "@/lib/minutesDom"
import { parseMinutes, toMarkdown, type Minutes } from "@/lib/minutes"

export type PaneState = "input" | "loading" | "result"

interface MinutesPaneProps {
  state: PaneState
  minutes: string
  title: string
}

export function MinutesPane({ state, minutes, title }: MinutesPaneProps) {
  if (state === "loading") return <LoadingDoc />
  if (state === "result") return <ResultDoc minutes={minutes} title={title} />
  return <EmptyDoc />
}

function EmptyDoc() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 px-8 py-16 text-center">
      <div className="rounded-full border border-line bg-card p-3">
        <FileText className="size-6 text-muted-foreground" aria-hidden />
      </div>
      <div className="max-w-sm space-y-2">
        <h2 className="font-heading text-lg font-semibold text-foreground">
          Your minutes appear here
        </h2>
        <p className="text-sm leading-relaxed text-muted-foreground">
          Add a transcript and your notes, then generate. The result is a formal
          محضر اجتماع you can edit in place and export to PDF.
        </p>
      </div>
    </div>
  )
}

const STAGES = [
  "Reading the transcript…",
  "Mapping topics from your notes…",
  "Summarizing by topic…",
  "Drafting the minutes…",
]

function LoadingDoc() {
  const [stage, setStage] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 2200)
    return () => clearInterval(id)
  }, [])
  return (
    <div className="px-8 py-10 sm:px-12">
      <div className="mx-auto max-w-[68ch] space-y-6">
        <p className="flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
          <span className="size-1.5 animate-pulse rounded-full bg-oxide" />
          {STAGES[stage]}
        </p>
        <Skeleton className="h-7 w-2/3" />
        <div className="space-y-2.5">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-4/5" />
        </div>
        <Skeleton className="h-5 w-1/2" />
      </div>
    </div>
  )
}

interface ResultDocProps {
  minutes: string
  title: string
}

function ResultDoc({ minutes, title }: ResultDocProps) {
  const [model, setModel] = useState<Minutes>(() => parseMinutes(minutes))
  const [editing, setEditing] = useState(false)
  const [copied, setCopied] = useState(false)

  // Re-parse only when a NEW generation arrives (inline edits live in `model`).
  useEffect(() => setModel(parseMinutes(minutes)), [minutes])

  const docTitle = title || model.title || "meeting"

  async function copy() {
    await navigator.clipboard.writeText(toMarkdown(model))
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  function download() {
    const blob = new Blob([toMarkdown(model) + "\n"], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${docTitle.replace(/\s+/g, "-").toLowerCase()}-minutes.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  function exportPdf() {
    const body = renderToStaticMarkup(<DefaultTemplate minutes={model} editable={false} />)
    const win = window.open("", "_blank", "width=900,height=1200")
    if (!win) return
    win.document.open()
    win.document.write(buildStandaloneHtml(body, docTitle))
    win.document.close()
    win.focus()
    // Print once the web fonts have actually loaded (Arabic needs Amiri, not a
    // serif fallback). The timer is a safety net if fonts.ready never settles.
    let printed = false
    const printOnce = () => {
      if (printed) return
      printed = true
      win.print()
    }
    setTimeout(printOnce, 2000)
    win.document.fonts.ready.then(printOnce, printOnce)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-1.5 border-b border-line bg-paper/85 px-4 py-2.5 backdrop-blur">
        <Button
          variant={editing ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setEditing((e) => !e)}
        >
          {editing ? <Eye className="size-4" /> : <Pencil className="size-4" />}
          {editing ? "Done" : "Edit"}
        </Button>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" onClick={copy}>
            {copied ? <Check className="size-4 text-oxide" /> : <Copy className="size-4" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button variant="ghost" size="sm" onClick={download}>
            <Download className="size-4" />
            .md
          </Button>
          <Button variant="ghost" size="sm" onClick={exportPdf}>
            <FileDown className="size-4" />
            PDF
          </Button>
        </div>
      </div>
      {editing && (
        <p className="bg-[var(--oxide-soft)] px-6 py-1.5 text-center text-xs text-muted-foreground">
          Fill each person's الجهة in قائمة الحضور — the المسؤول column updates automatically.
        </p>
      )}
      <div className="print-area overflow-y-auto px-8 py-10 sm:px-12">
        <DefaultTemplate minutes={model} editable={editing} onChange={setModel} />
      </div>
    </div>
  )
}
