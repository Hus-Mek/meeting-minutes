import { useRef } from "react"
import { LayoutTemplate, Paperclip, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { TEMPLATES } from "@/components/templates/registry"

// The output-template chooser — picked BEFORE generating, alongside the other
// inputs. Either a built-in template, or the user's own uploaded .docx (which the
// backend fills exactly). An upload takes precedence, so the built-in select is
// disabled while one is attached.
interface TemplatePickerProps {
  templateId: string
  uploadedTemplate: File | null
  onTemplateChange: (id: string) => void
  onUploadTemplate: (file: File | null) => void
}

export function TemplatePicker({
  templateId,
  uploadedTemplate,
  onTemplateChange,
  onUploadTemplate,
}: TemplatePickerProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  return (
    <section className="flex flex-col gap-2">
      <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        قالب الإخراج · Output template
      </Label>

      <Select value={templateId} onValueChange={onTemplateChange} disabled={Boolean(uploadedTemplate)}>
        <SelectTrigger className="h-9 gap-1.5 bg-card text-sm" aria-label="Output template" dir="rtl">
          <LayoutTemplate className="size-3.5 shrink-0 opacity-60" aria-hidden />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {TEMPLATES.map((t) => (
            <SelectItem key={t.id} value={t.id} className="text-sm" dir="rtl">
              {t.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        className="hidden"
        onChange={(e) => {
          const file = e.currentTarget.files?.[0]
          if (file) onUploadTemplate(file)
          e.currentTarget.value = "" // allow re-selecting the same file
        }}
      />

      {uploadedTemplate ? (
        <div className="flex items-center justify-between gap-2 rounded border border-line bg-card px-2.5 py-1.5 text-xs">
          <span
            className="flex min-w-0 items-center gap-1.5 text-muted-foreground"
            title={uploadedTemplate.name}
          >
            <Paperclip className="size-3.5 shrink-0 opacity-60" aria-hidden />
            <span className="truncate">{uploadedTemplate.name}</span>
          </span>
          <button
            type="button"
            aria-label="Remove uploaded template"
            onClick={() => onUploadTemplate(null)}
            className="shrink-0 opacity-60 hover:opacity-100"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ) : (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="justify-start gap-2 bg-card"
          onClick={() => inputRef.current?.click()}
        >
          <Paperclip className="size-4" />
          Upload my .docx template
        </Button>
      )}

      <p className="text-xs text-muted-foreground">
        Choose a built-in template, or upload your own .docx to render the minutes into it exactly.
      </p>
    </section>
  )
}
