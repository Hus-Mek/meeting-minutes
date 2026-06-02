import { useState } from "react"
import { FileJson, UploadCloud, X } from "lucide-react"
import type { InspectResult } from "@/lib/api"
import { cn } from "@/lib/utils"

interface DropzoneProps {
  file: File | null
  onSelect: (file: File | null) => void
  inspect: InspectResult | null
  inspecting: boolean
  inspectError: string | null
}

export function Dropzone({ file, onSelect, inspect, inspecting, inspectError }: DropzoneProps) {
  const [dragging, setDragging] = useState(false)

  function pick(files: FileList | null) {
    const next = files?.[0] ?? null
    onSelect(next)
  }

  if (file) {
    return (
      <div className="rounded-md border border-border bg-card px-3.5 py-3">
        <div className="flex items-center gap-3">
          <FileJson className="size-5 shrink-0 text-oxide" aria-hidden />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-foreground">{file.name}</p>
            <p className="text-xs text-muted-foreground">
              {inspecting
                ? "Reading…"
                : inspectError
                  ? inspectError
                  : inspect
                    ? `${inspect.segment_count} segments · ${inspect.speakers.length} ${
                        inspect.speakers.length === 1 ? "speaker" : "speakers"
                      } · ${inspect.duration}`
                    : `${(file.size / 1024).toFixed(0)} KB`}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onSelect(null)}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            aria-label="Remove transcript"
          >
            <X className="size-4" />
          </button>
        </div>
      </div>
    )
  }

  return (
    <label
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        pick(e.dataTransfer.files)
      }}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-8 text-center transition-colors",
        dragging
          ? "border-oxide bg-[var(--accent)]"
          : "border-border bg-card hover:border-oxide/60 hover:bg-accent/40",
      )}
    >
      <UploadCloud
        className={cn("size-6", dragging ? "text-oxide" : "text-muted-foreground")}
        aria-hidden
      />
      <div className="text-sm">
        <span className="font-medium text-foreground">Drop transcript</span>
        <span className="text-muted-foreground"> or browse</span>
      </div>
      <p className="text-xs text-muted-foreground">Diarized JSON · speaker, start, end, text</p>
      <input
        type="file"
        accept=".json,application/json"
        className="sr-only"
        onChange={(e) => pick(e.target.files)}
      />
    </label>
  )
}
