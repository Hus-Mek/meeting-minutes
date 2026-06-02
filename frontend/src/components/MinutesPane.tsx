import { useRef, useEffect, useState } from "react"
import Markdown from "react-markdown"
import remarkGfm from "remark-gfm"
import TurndownService from "turndown"
import { gfm } from "turndown-plugin-gfm"
import { Check, Copy, Download, Eye, FileText, Pencil, Printer } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"

// Convert the edited document HTML back to Markdown so Copy/Download stay clean .md.
const turndown = new TurndownService({ headingStyle: "atx", bulletListMarker: "-" })
turndown.use(gfm)

export type PaneState = "input" | "loading" | "result"

interface MinutesPaneProps {
  state: PaneState
  minutes: string
  title: string
  onChange?: (minutes: string) => void
}

export function MinutesPane({ state, minutes, title, onChange }: MinutesPaneProps) {
  if (state === "loading") return <LoadingDoc />
  if (state === "result") return <ResultDoc minutes={minutes} title={title} onChange={onChange} />
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
          Add a transcript and your notes, then generate. The result reads like a clean,
          topic-by-topic memo — grounded in the transcript, weighted by your notes.
        </p>
      </div>
      <div aria-hidden className="w-full max-w-sm space-y-2 pt-4 opacity-40">
        <div className="h-2.5 w-1/3 rounded bg-line" />
        <div className="h-2 w-full rounded bg-line" />
        <div className="h-2 w-5/6 rounded bg-line" />
        <div className="mt-4 h-2.5 w-2/5 rounded bg-line" />
        <div className="h-2 w-full rounded bg-line" />
        <div className="h-2 w-3/4 rounded bg-line" />
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
        <div className="space-y-2.5">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-10/12" />
        </div>
      </div>
    </div>
  )
}

interface ResultDocProps {
  minutes: string
  title: string
}

interface ResultDocProps2 extends ResultDocProps {
  onChange?: (minutes: string) => void
}

function ResultDoc({ minutes, title, onChange }: ResultDocProps2) {
  const previewRef = useRef<HTMLElement>(null)
  const editRef = useRef<HTMLElement>(null)
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editHtml, setEditHtml] = useState("")

  // The editable surface is fully UNCONTROLLED while typing — we never write state
  // back into it (that's what caused the caret to jump). We only read it back to
  // Markdown when finishing or exporting.
  function liveMarkdown(): string {
    if (editing && editRef.current) return turndown.turndown(editRef.current.innerHTML)
    return minutes
  }

  function startEdit() {
    setEditHtml(previewRef.current?.innerHTML ?? "")
    setEditing(true)
  }

  function finishEdit() {
    if (editRef.current) onChange?.(turndown.turndown(editRef.current.innerHTML))
    setEditing(false)
  }

  async function copy() {
    await navigator.clipboard.writeText(liveMarkdown())
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  function download() {
    const blob = new Blob([liveMarkdown() + "\n"], { type: "text/markdown" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${(title || "meeting").replace(/\s+/g, "-").toLowerCase()}-minutes.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="no-print sticky top-0 z-10 flex items-center justify-between gap-1.5 border-b border-line bg-paper/85 px-4 py-2.5 backdrop-blur">
        <Button
          variant={editing ? "secondary" : "ghost"}
          size="sm"
          onClick={editing ? finishEdit : startEdit}
          disabled={!onChange}
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
            Download
          </Button>
          <Button variant="ghost" size="sm" onClick={() => window.print()}>
            <Printer className="size-4" />
            Print
          </Button>
        </div>
      </div>
      {editing && (
        <p className="no-print bg-[var(--oxide-soft)] px-6 py-1.5 text-center text-xs text-muted-foreground">
          Click in the document and edit directly. Press <strong>Done</strong> to save your changes.
        </p>
      )}
      {/* Both surfaces are kept mounted so the caret never resets; we just toggle which is shown. */}
      <div className={editing ? "hidden" : "overflow-y-auto px-8 py-10 sm:px-12"}>
        <article ref={previewRef} dir="auto" className="print-area minutes-doc mx-auto">
          <Markdown remarkPlugins={[remarkGfm]}>{minutes}</Markdown>
        </article>
      </div>
      {editing && (
        <div className="overflow-y-auto px-8 py-10 sm:px-12">
          <article
            ref={editRef}
            dir="auto"
            contentEditable
            suppressContentEditableWarning
            aria-label="Edit minutes"
            className="print-area minutes-doc mx-auto rounded-md p-1 outline-none ring-1 ring-[var(--oxide)]/25 focus-within:ring-2 focus-within:ring-ring"
            dangerouslySetInnerHTML={{ __html: editHtml }}
          />
        </div>
      )}
    </div>
  )
}
