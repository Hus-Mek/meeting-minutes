import { useEffect, useRef, useState } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { toast } from "sonner"
import { Check, Copy, Download, Eye, FileDown, FileText, FileType2, LayoutTemplate, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { DEFAULT_TEMPLATE_ID, getTemplate } from "@/components/templates/registry"
import { exportMinutesDocx } from "@/lib/api"
import { buildStandaloneHtml } from "@/lib/minutesDom"
import { parseMinutes, toMarkdown, type Minutes } from "@/lib/minutes"

export type PaneState = "input" | "loading" | "result"

interface MinutesPaneProps {
  state: PaneState
  minutes: string
  title: string
  templateId?: string
  uploadedTemplate?: File | null
}

export function MinutesPane({
  state,
  minutes,
  title,
  templateId = DEFAULT_TEMPLATE_ID,
  uploadedTemplate = null,
}: MinutesPaneProps) {
  // Keep the result mounted once minutes exist, so in-place edits survive a
  // re-generate (it shows a "regenerating" hint instead of unmounting and
  // re-parsing from scratch). The first-ever generation still shows LoadingDoc.
  if (minutes)
    return (
      <ResultDoc
        minutes={minutes}
        title={title}
        templateId={templateId}
        uploadedTemplate={uploadedTemplate}
        regenerating={state === "loading"}
      />
    )
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
          Add a transcript and your notes, then generate. The result is rendered into
          your chosen محضر اجتماع template — exactly as it downloads.
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
  templateId: string
  uploadedTemplate: File | null
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

function ResultDoc({ minutes, title, templateId, uploadedTemplate, regenerating = false }: ResultDocProps) {
  const [model, setModel] = useState<Minutes>(() => parseMinutes(minutes))
  const [copied, setCopied] = useState(false)
  const [exporting, setExporting] = useState<null | "docx" | "pdf">(null)
  const [view, setView] = useState<"exact" | "edit">("exact")
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const pdfUrlRef = useRef<string | null>(null)

  // A new generation refreshes the content but preserves the orgs the user typed.
  useEffect(() => setModel((prev) => mergeOrgs(parseMinutes(minutes), prev)), [minutes])

  const Template = getTemplate(templateId).Component
  const docTitle = title || model.title || "meeting"
  const md = toMarkdown(model)
  const templateLabel = uploadedTemplate ? uploadedTemplate.name : getTemplate(templateId).name

  // The exact preview IS the rendered document: fill the chosen .docx server-side,
  // convert to PDF, and show it inline. Re-rendered when the exact view is shown for
  // the current content (edits happen in the edit view, which skips this fetch).
  useEffect(() => {
    if (view !== "exact") return
    let cancelled = false
    setPdfLoading(true)
    setPdfError(null)
    exportMinutesDocx(md, { template: uploadedTemplate, format: "pdf", filename: docTitle })
      .then((blob) => {
        if (cancelled) return
        if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = URL.createObjectURL(blob)
        setPdfUrl(pdfUrlRef.current)
      })
      .catch((err) => {
        if (!cancelled) setPdfError(err instanceof Error ? err.message : "Could not render the exact preview")
      })
      .finally(() => {
        if (!cancelled) setPdfLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [view, md, uploadedTemplate, docTitle])

  // Release the last object URL when the component unmounts.
  useEffect(
    () => () => {
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
    },
    [],
  )

  async function copy() {
    await navigator.clipboard.writeText(md)
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
    triggerBlobDownload(new Blob([md + "\n"], { type: "text/markdown" }), "md")
  }

  async function exportFile(format: "docx" | "pdf") {
    setExporting(format)
    try {
      const blob = await exportMinutesDocx(md, { template: uploadedTemplate, format, filename: docTitle })
      triggerBlobDownload(blob, format)
    } catch (err) {
      if (format === "pdf") {
        printPreview() // fall back to browser print; it owns its own messaging
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
    if (!win) {
      toast.error("Couldn't open a print window — allow popups, or use the .docx export.")
      return
    }
    toast.message("Server PDF unavailable — printing the preview instead.")
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
        <div className="flex min-w-0 items-center gap-1.5">
          <Button
            variant={view === "edit" ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setView((v) => (v === "edit" ? "exact" : "edit"))}
          >
            {view === "edit" ? <Eye className="size-4" /> : <Pencil className="size-4" />}
            {view === "edit" ? "Exact preview" : "Edit"}
          </Button>
          <span
            className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground"
            title={templateLabel}
          >
            <LayoutTemplate className="size-3.5 shrink-0 opacity-60" aria-hidden />
            <span className="max-w-[160px] truncate" dir="auto">
              {templateLabel}
            </span>
          </span>
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

      {view === "edit" ? (
        <>
          <p className="bg-[var(--oxide-soft)] px-6 py-1.5 text-center text-xs text-muted-foreground">
            Fill each person's الجهة in قائمة الحضور — the المسؤول column updates automatically, then
            switch back to Exact preview.
          </p>
          <div className="print-area overflow-y-auto px-8 py-10 sm:px-12">
            <Template minutes={model} editable onChange={setModel} />
          </div>
        </>
      ) : (
        <div className="relative min-h-0 flex-1 bg-muted/30">
          {pdfLoading && (
            <p className="absolute inset-x-0 top-0 z-10 flex items-center justify-center gap-2 bg-paper/85 px-6 py-1.5 text-center text-xs text-muted-foreground backdrop-blur">
              <Loader2 className="size-3 animate-spin" aria-hidden />
              Rendering the exact document…
            </p>
          )}
          {pdfError ? (
            <div className="h-full overflow-y-auto px-8 py-10 sm:px-12">
              <p className="mx-auto mb-4 max-w-[68ch] rounded border border-line bg-card px-3 py-2 text-xs text-muted-foreground">
                Exact preview unavailable ({pdfError}). Showing an approximate preview — the downloaded
                .docx is still exact.
              </p>
              <Template minutes={model} editable={false} />
            </div>
          ) : (
            pdfUrl && <iframe src={pdfUrl} title="Exact document preview" className="h-full w-full border-0" />
          )}
        </div>
      )}
    </div>
  )
}
