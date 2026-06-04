import { useState, type ReactNode } from "react"
import { Check, Copy, ExternalLink, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface ClaudeCodeSetupGuideProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onUseCowork: () => void
}

const INSTALL_COMMAND = "npm install -g @anthropic-ai/claude-code"
const LOGIN_COMMAND = "claude"
const COPIED_RESET_MS = 1500

export function ClaudeCodeSetupGuide({
  open,
  onOpenChange,
  onUseCowork,
}: ClaudeCodeSetupGuideProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Set up Claude Code</DialogTitle>
          <DialogDescription>
            Claude Code needs to be ready on this PC. If you installed the app bundle,
            it&apos;s already here — just log in: open the Meeting Minutes icon in your
            system tray (bottom-right of the taskbar) and choose &quot;Log in to
            Claude&quot;. Otherwise follow the steps below, or use Cowork now — no setup
            needed.
          </DialogDescription>
        </DialogHeader>

        <ol className="flex flex-col gap-5">
          <Step
            number={1}
            heading="Install Node.js"
            illustration="/setup/step-1-node.svg"
            alt="A browser window on nodejs.org with a Download Node.js LTS button"
          >
            <p>
              Download and install Node.js (LTS) from nodejs.org. Keep all the
              default options when the installer asks.
            </p>
            <Button asChild variant="outline" size="sm" className="mt-2 w-fit">
              <a
                href="https://nodejs.org"
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink />
                Open nodejs.org
              </a>
            </Button>
          </Step>

          <Step
            number={2}
            heading="Install Claude Code"
            illustration="/setup/step-2-install.svg"
            alt="A Command Prompt window running npm install for the Claude Code package"
          >
            <p>
              Open Command Prompt (press the Windows key, type{" "}
              <span className="font-mono text-foreground">cmd</span>, then press
              Enter) and run this command:
            </p>
            <CommandBlock command={INSTALL_COMMAND} />
          </Step>

          <Step
            number={3}
            heading="Log in to Claude"
            illustration="/setup/step-3-login.svg"
            alt="Running the claude command opens a browser window to log in to Claude"
          >
            <p>
              Run the command below, then log in with your Claude account in the
              browser window that opens:
            </p>
            <CommandBlock command={LOGIN_COMMAND} />
          </Step>

          <Step
            number={4}
            heading="You're all set"
            illustration="/setup/step-4-done.svg"
            alt="A success checkmark confirming Claude Code is ready to use"
          >
            <p>Reopen Meeting Minutes (or just click Generate again).</p>
          </Step>
        </ol>

        <DialogFooter className="sm:justify-between">
          <Button variant="default" onClick={onUseCowork} className="gap-1.5">
            <Sparkles />
            Use Cowork instead (no setup)
          </Button>
          <DialogClose asChild>
            <Button variant="outline">I&apos;ve installed it</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

interface StepProps {
  number: number
  heading: string
  illustration: string
  alt: string
  children: ReactNode
}

function Step({ number, heading, illustration, alt, children }: StepProps) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground"
      >
        {number}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <h3 className="text-sm font-semibold text-foreground">{heading}</h3>
        <div className="flex flex-col gap-1 text-sm leading-relaxed text-muted-foreground">
          {children}
        </div>
        <img
          src={illustration}
          alt={alt}
          className="mt-1 w-full rounded-lg border border-border"
        />
      </div>
    </li>
  )
}

interface CommandBlockProps {
  command: string
}

function CommandBlock({ command }: CommandBlockProps) {
  const [copied, setCopied] = useState(false)

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      toast.success("Copied")
      setTimeout(() => setCopied(false), COPIED_RESET_MS)
    } catch {
      toast.error("Couldn't copy — select the text and copy it manually")
    }
  }

  return (
    <div className="mt-1 flex items-center gap-2">
      <code className="min-w-0 flex-1 break-all rounded-md bg-muted px-3 py-2 font-mono text-sm text-foreground">
        {command}
      </code>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={handleCopy}
        className="shrink-0"
        aria-label={copied ? "Copied" : "Copy command"}
      >
        {copied ? <Check /> : <Copy />}
        {copied ? "Copied" : "Copy"}
      </Button>
    </div>
  )
}
