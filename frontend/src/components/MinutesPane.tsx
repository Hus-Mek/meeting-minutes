import { useEffect, useRef, useState, type ChangeEvent } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { toast } from "sonner"
import { Check, Copy, Download, Eye, FileDown, FileText, FileType2, LayoutTemplate, Loader2, Paperclip, Pencil, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Select, SelectContent, SelectItem, SelectTrigger } from "@/components/ui/select"
import { DEFAULT_TEMPLATE_ID, getTemplate, TEMPLATES } from "@/components/templates/registry"
import { exportMinutesDocx } from "@/lib/api"
import { buildStandaloneHtml } from "@/lib/minutesDom"
import { parseMinutes, toMarkdown, type Minutes } from "@/lib/minutes"

export type PaneState = "input" | "loading" | "result"

interface MinutesPaneProps {
  state: PaneState
  minutes: string
  title: string
}

export function MinutesPane({ state, minutes, title }: MinutesPaneProps) {
  // Keep the result mounted once minutes exist, so in-place edits survive a
  // re-generate (it shows a "regenerating" hint instead of unmounting and
  // re-parsing from scratch). The first-ever generation still shows LoadingDoc.
  if (minutes) return <ResultDoc minutes={minutes} title={title} regenerating={state === "loading"} />
  if (state === "loading") return <LoadingDoc />
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
  regenerating?: boolean
}

// Carry the user's manually-entered الجهة values onto a freshly parsed model so a
// re-generate keeps them (task/summary/points still refresh with the new content).
function mergeOrgs(next: Minutes, prev: Minutes): Minutes {
  const prevOrg = new Map(prev.attendees.map((a) => [a.name.trim(), a.org]))
  return {
    ...next,
    attendees: next.attendees.map((a) => {
      const saved = prevOrg.get(a.name.trim())
      return saved?.trim() && !a.org.trim() ? { ...a, org: saved } : a
    }),
  }
}

function ResultDoc({ minutes, title, regenerating = false }: ResultDocProps) {
  const [model, setModel] = useState<Minutes>(() => parseMinutes(minutes))
  const [editing, setEditing] = useState(false)
  const [copied, setCopied] = useState(false)
  const [templateId, setTemplateId] = useState(DEFAULT_TEMPLATE_ID)
  const [uploadedTemplate, setUploadedTemplate] = useState<File | null>(null)
  const [exporting, setExporting] = useState<null | "docx" | "pdf">(null)
  const templateInputRef = useRef<HTMLInputElement>(null)

  // A new generation refreshes the content but preserves the orgs the user typed.
  useEffect(() => setModel((prev) => mergeOrgs(parseMinutes(minutes), prev)), [minutes])

  const Template = getTemplate(templateId).Component
  const docTitle = title || model.title || "meeting"

  async function copy() {
    await navigator.clipboard.writeText(toMarkdown(model))
    setCopied(true)
    setTimeout(() => setCopied(false), 1600)
  }

  function triggerBlobDownload(blob: Blob, ext: string) {
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${docTitle.replace(/\s+/g, "-").toLowerCase()}-minutes.${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }

  function download() {
    triggerBlobDownload(new Blob([toMarkdown(model) + "\n"], { type: "text/markdown" }), "md")
  }

  // Render the current minutes into the user's .docx template (or the bundled one)
  // server-side and download it. PDF goes through LibreOffice for true fidelity, and
  // falls back to printing the on-screen preview if the server can't produce one.
  async function exportFile(format: "docx" | "pdf") {
    setExporting(format)
    try {
      const blob = await exportMinutesDocx(toMarkdown(model), {
        template: uploadedTemplate,
        format,
        filename: docTitle,
      })
      triggerBlobDownload(blob, format)
    } catch (err) {
      if (format === "pdf") {
        toast.message("Server PDF unavailable — printing the preview instead.")
        printPreview()
      } else {
        toast.error(err instanceof Error ? err.message : "Could not export the .docx")
      }
    } finally {
      setExporting(null)
    }
  }

  function printPreview() {
    const body = renderToStaticMarkup(<Template minutes={model} editable={false} />)
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

  function onTemplatePick(e: ChangeEvent<HTMLInputElement>) {
    const file = e.currentTarget.files?.[0]
    if (file) {
      setUploadedTemplate(file)
      toast.success(`Template set: ${file.name}`)
    }
    e.currentTarget.value = "" // allow re-selecting the same file
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between gap-1.5 border-b border-line bg-paper/85 px-4 py-2.5 backdrop-blur">
        <div className="flex min-w-0 items-center gap-1.5">
          <Button
            variant={editing ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setEditing((e) => !e)}
          >
            {editing ? <Eye className="size-4" /> : <Pencil className="size-4" />}
            {editing ? "Done" : "Edit"}
          </Button>
          <Select value={templateId} onValueChange={setTemplateId}>
            <SelectTrigger
              className="h-8 w-[190px] gap-1.5 bg-card text-xs"
              aria-label="Template / القالب"
            >
              <LayoutTemplate className="size-3.5 shrink-0 opacity-60" aria-hidden />
              <span className="truncate" dir="rtl">
                {getTemplate(templateId).name}
              </span>
            </SelectTrigger>
            <SelectContent>
              {TEMPLATES.map((t) => (
                <SelectItem key={t.id} value={t.id} className="text-xs" dir="rtl">
                  {t.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <input
            ref={templateInputRef}
            type="file"
            accept=".docx"
            className="hidden"
            onChange={onTemplatePick}
          />
          {uploadedTemplate ? (
            <span
              className="flex items-center gap-1 rounded bg-card px-1.5 py-1 text-xs text-muted-foreground"
              title={uploadedTemplate.name}
            >
              <Paperclip className="size-3 shrink-0 opacity-60" aria-hidden />
              <span className="max-w-[90px] truncate">{uploadedTemplate.name}</span>
              <button
                type="button"
                aria-label="Remove template"
                onClick={() => setUploadedTemplate(null)}
                className="opacity-60 hover:opacity-100"
              >
                <X className="size-3" />
              </button>
            </span>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => templateInputRef.current?.click()}
              title="Upload your own .docx template"
            >
              <Paperclip className="size-4" />
              Template
            </Button>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" onClick={copy}>
            {copied ? <Check className="size-4 text-oxide" /> : <Copy className="size-4" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          <Button variant="ghost" size="sm" onClick={download}>
            <Download className="size-4" />
            .md
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => exportFile("docx")}
            disabled={exporting !== null}
            title="Download an exact .docx (your template)"
          >
            {exporting === "docx" ? <Loader2 className="size-4 animate-spin" /> : <FileType2 className="size-4" />}
            .docx
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => exportFile("pdf")}
            disabled={exporting !== null}
            title="Download a PDF rendered from the .docx"
          >
            {exporting === "pdf" ? <Loader2 className="size-4 animate-spin" /> : <FileDown className="size-4" />}
            PDF
          </Button>
        </div>
      </div>
      {regenerating && (
        <p className="flex items-center justify-center gap-2 bg-[var(--oxide-soft)] px-6 py-1.5 text-center text-xs text-muted-foreground">
          <Loader2 className="size-3 animate-spin" aria-hidden />
          Regenerating… your الجهة edits are kept.
        </p>
      )}
      {editing && (
        <p className="bg-[var(--oxide-soft)] px-6 py-1.5 text-center text-xs text-muted-foreground">
          Fill each person's الجهة in قائمة الحضور — the المسؤول column updates automatically. Add a row
          for anyone missing.
        </p>
      )}
      <div className="print-area overflow-y-auto px-8 py-10 sm:px-12">
        <Template minutes={model} editable={editing} onChange={setModel} />
      </div>
    </div>
  )
}
