import { useState } from "react"
import { Loader2, LogIn, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { claudeLogin } from "@/lib/api"
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

// The app bundles Node.js + the Claude Code CLI, so there is nothing to install —
// the only one-time step is signing in. Keep this guide login-focused.
const LOGIN_STEPS = [
  'Click "Log in to Claude" below — a window opens on this PC.',
  "Sign in with your Claude account in the browser that opens, then close that window.",
  'Come back here and click "Generate minutes" — that\'s it.',
]

export function ClaudeCodeSetupGuide({
  open,
  onOpenChange,
  onUseCowork,
}: ClaudeCodeSetupGuideProps) {
  const [loggingIn, setLoggingIn] = useState(false)

  async function handleLogin() {
    setLoggingIn(true)
    try {
      await claudeLogin()
      toast.success(
        "Opening the Claude login window — sign in there, then come back and click Generate.",
      )
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Couldn't start the Claude login")
    } finally {
      setLoggingIn(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Log in to Claude</DialogTitle>
          <DialogDescription>
            Meeting Minutes already includes everything it needs — there&apos;s nothing
            to install. Just sign in once with your Claude account to start generating
            minutes. Prefer not to? Use Cowork instead — no sign-in needed.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/40 p-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-foreground">
            Sign in with your Claude account to get started.
          </p>
          <Button onClick={handleLogin} disabled={loggingIn} className="shrink-0 gap-1.5">
            {loggingIn ? <Loader2 className="animate-spin" /> : <LogIn />}
            Log in to Claude
          </Button>
        </div>

        <ol className="flex flex-col gap-3">
          {LOGIN_STEPS.map((step, index) => (
            <li key={index} className="flex gap-3">
              <span
                aria-hidden="true"
                className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground"
              >
                {index + 1}
              </span>
              <p className="flex-1 text-sm leading-relaxed text-muted-foreground">{step}</p>
            </li>
          ))}
        </ol>

        <img
          src="/setup/step-3-login.svg"
          alt="Logging in opens a browser window to sign in to your Claude account"
          className="w-full rounded-lg border border-border"
        />

        <DialogFooter className="sm:justify-between">
          <Button variant="default" onClick={onUseCowork} className="gap-1.5">
            <Sparkles />
            Use Cowork instead (no setup)
          </Button>
          <DialogClose asChild>
            <Button variant="outline">I&apos;ve logged in</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
