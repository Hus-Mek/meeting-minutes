# Windows Packaging

This directory holds everything needed to ship **Meeting Minutes** as a
one-click Windows app for non-technical users. The pipeline turns the FastAPI
backend + prebuilt React SPA into a single installer:

> **`dist/installer/MeetingMinutes-Setup.exe`**

This document is for the maintainer who builds and ships that installer. A short
[end-user note](#end-user-note) is at the bottom.

---

## 1. What gets built & the end-user flow

The build produces exactly **one artifact**: `MeetingMinutes-Setup.exe`, a
per-user Inno Setup installer (no admin rights, no UAC elevation required).

The end-user flow:

1. Download and run `MeetingMinutes-Setup.exe`.
2. The installer drops the app under the per-user program folder and creates a
   **Start Menu** shortcut (plus an optional **Desktop** shortcut).
3. Double-click the shortcut. A teal icon appears in the **system tray** and the
   **default browser opens the app** automatically.
4. Use the app in the browser.
5. To stop it, right-click the tray icon and choose **Quit** (this is the only
   way to fully stop the server — see [Limitations](#6-limitations)).

There is **no API key** to enter and **no configuration** to ship. The installer
**bundles Node.js + the Claude Code CLI**, and the launcher prefers a `claude` the
machine already has (e.g. from the Claude desktop app or an npm install), falling
back to the bundled copy. To avoid leaving a redundant second Claude Code install,
the installer **skips laying down the bundled CLI when the PC already has one**
(Approach B — see [§7](#7-bundled-claude-code-cli-approach-b)); portable Node.js is
always installed. The only one-time step left for the user is to **log in to Claude**
(tray icon → *Log in to Claude*) using their own subscription — nothing metered or
secret is bundled. **Cowork** remains a zero-setup fallback.

---

## 2. Wrapper architecture

Three layers turn the web app into a desktop app:

1. **Launcher — `meeting_minutes/desktop.py`.**
   The frozen EXE's entry point. Its `main()`:
   - picks a free local TCP port (`find_free_port`),
   - starts uvicorn bound to **`127.0.0.1` only** (never `0.0.0.0`, since the
     app has no auth) in a background thread,
   - polls `/api/health` until the server answers (or times out at 30 s, then
     shows a friendly error dialog),
   - opens the default browser at the app URL,
   - shows a **system-tray icon** (Open / Quit) and stays resident until the
     user clicks **Quit**, which stops the server cleanly.

   It is a *windowed* app (no console). Because frozen windowed apps have no
   `stdout`/`stderr`, the launcher redirects logging to a per-user log file at
   `%LOCALAPPDATA%\MeetingMinutes\app.log`.

2. **Freeze — PyInstaller ONEDIR.**
   `packaging/meeting_minutes.spec` freezes the launcher and all dependencies
   into a directory tree `dist/MeetingMinutes/` containing `MeetingMinutes.exe`
   plus an `_internal/` folder (Python runtime, deps, bundled data). ONEDIR (not
   ONEFILE) is used for faster startup and friendlier antivirus behavior.

3. **Installer — Inno Setup 6.**
   `packaging/installer.iss` packages the `dist/MeetingMinutes/` tree into the
   single per-user `MeetingMinutes-Setup.exe`, with Start Menu and optional Desktop
   shortcuts and an uninstaller. Its `[Code]` section detects an existing `claude`
   and **conditionally skips the bundled CLI files** (Approach B —
   [§7](#7-bundled-claude-code-cli-approach-b)).

4. **Bundled runtime — portable Node.js + Claude Code CLI.**
   CI (and `build_windows.ps1`) download a portable Node.js and run
   `npm i -g @anthropic-ai/claude-code --prefix vendor/node`, which the spec
   bundles into the app. At startup `desktop._ensure_claude_runtime()` **prefers a
   `claude` the user already has** (PATH / known install locations) and only falls
   back to the bundled copy, wiring `CLAUDE_CODE_BIN` + `PATH` so the `claude.cmd`
   shim finds `node`. The tray menu's **Log in to Claude** opens an interactive
   `claude` for the one-time browser login.

---

## 3. Files involved

| File | Role |
|---|---|
| `meeting_minutes/desktop.py` | The launcher (EXE entry point): free port → uvicorn on 127.0.0.1 → wait for `/api/health` → open browser → system-tray (Open / **Log in to Claude** / Quit). `_ensure_claude_runtime()` prefers an existing `claude`, else wires the bundled `vendor/node`. Pure helpers are import-safe and unit-testable on headless Linux/CI. |
| `requirements-desktop.txt` | Desktop runtime deps layered on the server deps: `-r requirements.txt` plus `pystray` (tray icon + Quit) and `Pillow` (generates the in-memory tray image). PyInstaller is **not** here — it's a build-only tool installed by CI / the build script. |
| `packaging/make_icon.py` | Generates `packaging/app.ico` (brand teal `#00ABAF` badge + document glyph) entirely in code with Pillow — no committed binary icon. Consumed by both the spec (embedded in the EXE) and the installer (`SetupIconFile`). |
| `packaging/meeting_minutes.spec` | PyInstaller ONEDIR spec → `dist/MeetingMinutes/` (`MeetingMinutes.exe` + `_internal/`). Bundles `frontend/dist` → `frontend/dist` (bundle root, so `web.py`'s `parent.parent/frontend/dist` resolves), the prebuilt `sample_arabic_minutes.docx` → `meeting_minutes/templates`, and (when present) `vendor/node` → `vendor/node` (portable Node.js + the Claude Code CLI). UPX disabled (trips AV); `console=False`. |
| `packaging/installer.iss` | Inno Setup 6 script. Per-user install (`PrivilegesRequired=lowest`, no admin/UAC), x64, Start Menu + optional Desktop shortcuts, fixed `AppId` GUID for clean upgrades. Its `[Code]` `ShouldInstallBundledClaude` check skips the bundled CLI when the PC already has `claude` (Approach B). Outputs `../dist/installer/MeetingMinutes-Setup.exe`. |
| `packaging/sign_windows.ps1` | Authenticode-signs a binary (the EXE or the installer) with SHA-256 + an RFC 3161 timestamp, using a base64 PFX from `WINDOWS_PFX_BASE64` / `WINDOWS_PFX_PASSWORD`. A **no-op when no cert is configured**, so unsigned builds still succeed. Invoked twice by CI (see [§8](#8-code-signing-self-signed-internal-fleet)). |
| `packaging/make_selfsigned_cert.ps1` | One-time helper (run on Windows) to create a self-signed code-signing cert and export the `.pfx` (for the GitHub secret) + `.cer` (to deploy to the fleet's Trusted Publishers/Root). Prints the base64 for `WINDOWS_PFX_BASE64`. |
| `meeting_minutes/update.py` | Update checker: compares `meeting_minutes.__version__` against the latest GitHub release and reports a download link. Backs `GET /api/update/check` and the startup "update available" toast. Fails silently on any network error. |
| `packaging/build_windows.ps1` | One-shot **local** Windows build: frontend → isolated `.buildvenv` → install deps + PyInstaller → prebuild `.docx` template → `make_icon.py` → PyInstaller freeze → ISCC. Resolves the repo root itself, so cwd doesn't matter. |
| `.github/workflows/build-windows.yml` | **CI** build on `windows-latest`: same steps as the local script; installs Inno Setup via Chocolatey and invokes ISCC at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`. Optionally signs the EXE + installer when `WINDOWS_PFX_*` secrets are set. Uploads the installer as an artifact (and attaches it to a GitHub Release on tag pushes). |

Build-time artifacts (not committed): `packaging/app.ico`, `frontend/dist/`,
`meeting_minutes/templates/sample_arabic_minutes.docx`, `vendor/` (portable
Node.js + the Claude Code CLI), `.buildvenv/`, `dist/MeetingMinutes/`, and
`dist/installer/MeetingMinutes-Setup.exe`.

---

## 4. How to build

### Via CI (recommended)

The `build-windows` workflow runs on `windows-latest` and needs no local Windows
machine.

**Trigger it one of two ways:**

- **Push a version tag** matching `v*` (e.g. `git tag v1.0.0 && git push origin
  v1.0.0`). On a tag push the workflow also attaches the installer to the
  matching GitHub Release.
- **Run it manually** from the GitHub **Actions** tab → *build-windows* → *Run
  workflow* (`workflow_dispatch`).

**Get the installer:** open the completed workflow run and download the
**`MeetingMinutes-Setup`** artifact (it contains
`MeetingMinutes-Setup.exe`). For tagged builds it's also on the Release page.

### Locally on Windows

**Prerequisites:**

- **Node.js 20+** (and npm) — builds the React frontend.
- **Python 3.12** — preferably via the `py` launcher (`py -3.12`); the script
  falls back to `python` on PATH.
- **Inno Setup 6** — provides `ISCC.exe`. Get it from
  <https://jrsoftware.org/isdl.php>. The script uses `ISCC` on PATH, otherwise
  falls back to `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.

**Build:**

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

The script runs all steps end to end and prints the final path:
`dist\installer\MeetingMinutes-Setup.exe`.

---

## 5. Why the .docx template is pre-built and bundled

The Arabic minutes template (`meeting_minutes/templates/sample_arabic_minutes.docx`)
is **generated at packaging time** (`from meeting_minutes.sample_template import
build`) and bundled into the frozen app.

A per-user install lands the app under the program folder (`Program Files` when
installed machine-wide), which is **read-only** to a normal user at runtime. If
the app tried to *generate* the template on first launch, that write would fail.
Pre-building it means the frozen app only ever **reads** the template from its
bundle — never writes into the install directory. The spec copies it to
`meeting_minutes/templates` inside the bundle so the runtime path resolves
exactly as it does in development.

---

## 6. Limitations

- **PDF export still needs LibreOffice on the user's PC.** This is unchanged by
  packaging — the installer does **not** bundle LibreOffice. Generating Word
  minutes works out of the box; PDF export requires LibreOffice to be installed
  separately.
- **Each launch picks a fresh free port.** The app URL/port is not fixed; it's
  chosen at startup, so bookmarking the exact URL is not reliable. Use the tray
  icon's **Open** action to reopen the app.
- **Closing the browser tab does not quit the app.** The server keeps running in
  the background behind the tray icon. To fully stop it, right-click the tray
  icon and choose **Quit**.

---

## 7. Bundled Claude Code CLI (Approach B)

The installer ships portable **Node.js + the Claude Code CLI** so a fresh PC needs
only a one-time login. To avoid leaving a **redundant second Claude Code install**
on machines that already have one, `installer.iss` splits the file copy:

- **Node.js and everything else** is always installed.
- The **bundled CLI files** — the `claude.*` shims and the
  `…\node_modules\@anthropic-ai\…` package — are installed **only when no existing
  `claude` is detected**, via the `[Code]` function `ShouldInstallBundledClaude`.

> **Path note:** this is a PyInstaller **ONEDIR** build, so the bundled tree lives
> under the `_internal\` contents dir — the real path is
> `…\_internal\vendor\node\…`. The `installer.iss` `Excludes`/`Source` entries
> include that `_internal\` prefix; without it the Exclude would silently match
> nothing and the CLI would ship unconditionally.

Detection mirrors the resolution order in `meeting_minutes/llm.py`
(`ClaudeCodeClient._FALLBACK_PATHS`): `where claude` on the user's **PATH** first
(e.g. the npm global shim dir `%APPDATA%\npm`), then the known per-user install
locations (`%APPDATA%\npm`, `%LOCALAPPDATA%\Programs\claude`, `~\.local\bin`). The
result is cached because Inno calls a `Check` function once per matched file.

This is **fully offline** — the installer always contains the CLI; it just doesn't
*lay it down* when one is already present (the launcher uses the existing one at
runtime regardless). Trade-offs:

- A few flattened npm dependency folders may remain under `vendor\node\node_modules`
  when skipping — harmless dead weight, not a usable `claude` (no shim, no package).
- If an existing `claude` is broken, the bundle is still skipped; the user falls back
  to **Log in to Claude** / **Cowork**. This matches "prefer the existing install".

---

## 8. Code signing (self-signed, internal fleet)

Signing is **optional** and gated on two GitHub secrets. With them unset the build
still produces a working (unsigned) installer; with them set, CI signs both the app
EXE (before the installer is built) and the finished installer.

**Set it up once:**

1. On a Windows PC, generate a self-signed code-signing cert:
   ```powershell
   powershell -ExecutionPolicy Bypass -File packaging\make_selfsigned_cert.ps1 -Password 'a-strong-passphrase'
   ```
   This writes `meetingminutes-codesign.pfx` + `.cer` and prints the `.pfx` base64.
2. In the GitHub repo → **Settings → Secrets and variables → Actions**, add:
   - `WINDOWS_PFX_BASE64` — the printed base64 of the `.pfx`.
   - `WINDOWS_PFX_PASSWORD` — the passphrase from step 1.
3. Deploy the **`.cer`** to the fleet so those PCs trust the signature. Via Group
   Policy, import it into **Trusted Publishers** *and* **Trusted Root Certification
   Authorities** (Computer Configuration → Windows Settings → Security Settings →
   Public Key Policies). Only machines that trust the `.cer` get the SmartScreen /
   "Unknown publisher" suppression.

> **Self-signed ≠ external trust.** This suppresses warnings only on machines that
> trust your `.cer`. For distribution to the public, use an **EV/OV code-signing
> certificate** from a public CA (or Azure Trusted Signing) — then only the two
> secrets change; the workflow is the same.

The signing itself uses `Set-AuthenticodeSignature` (SHA-256 + an RFC 3161
timestamp, so signatures survive cert expiry) via `packaging/sign_windows.ps1`.

---

## 9. Versioning & the update checker

`meeting_minutes/__init__.py` `__version__` is the single source of truth for the
app version and **must be bumped in lockstep with `installer.iss`'s `AppVersion`**
for each release. `meeting_minutes/update.py` compares `__version__` against the
latest GitHub release (`GET /api/update/check`); when a newer one exists the SPA
shows a persistent "update available" toast with a **Download** link to the
installer asset. The repo is public, so the check needs no token (an optional
`MM_UPDATE_TOKEN` / `GITHUB_TOKEN` only lifts the anonymous rate limit).

**Release checklist:** bump `__version__` + `AppVersion` together → run tests
(`pytest`, `vitest`) and a build → commit → `git tag vX.Y.Z && git push origin
vX.Y.Z` → the `build-windows` workflow builds, (optionally) signs, and attaches the
installer to the matching Release.

---

## End-user note

> **Meeting Minutes** is a small app that runs on your own PC.
>
> 1. Run **MeetingMinutes-Setup.exe** to install it (no admin rights needed).
> 2. Open it from the **Start Menu** (or the Desktop shortcut). Your browser
>    will open the app automatically, and a small teal icon appears near the
>    clock (the **system tray**).
> 3. **The first time only:** right-click the tray icon and choose **Log in to
>    Claude**, then sign in with your Claude account in the window that opens.
>    (Or choose **Cowork** in the app to skip this entirely.)
> 4. When you're done, right-click that tray icon and choose **Quit**. Just
>    closing the browser tab does **not** close the app.
>
> No API key or manual install is required — Node.js and the Claude Code CLI come
> bundled. If you also want to export minutes as **PDF**, ask your IT/admin to
> install **LibreOffice** — Word export works without it.
