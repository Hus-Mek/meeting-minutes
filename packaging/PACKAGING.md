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

There is **no API key** to enter and **no configuration** to ship. The app
talks to the local **Claude Code CLI / Cowork** backend already on the machine,
so nothing metered or secret is bundled or requested.

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
   `packaging/installer.iss` packages the entire `dist/MeetingMinutes/` tree
   into the single per-user `MeetingMinutes-Setup.exe`, with Start Menu and
   optional Desktop shortcuts and an uninstaller.

---

## 3. Files involved

| File | Role |
|---|---|
| `meeting_minutes/desktop.py` | The launcher (EXE entry point): free port → uvicorn on 127.0.0.1 → wait for `/api/health` → open browser → system-tray Quit. Pure helpers are import-safe and unit-testable on headless Linux/CI. |
| `requirements-desktop.txt` | Desktop runtime deps layered on the server deps: `-r requirements.txt` plus `pystray` (tray icon + Quit) and `Pillow` (generates the in-memory tray image). PyInstaller is **not** here — it's a build-only tool installed by CI / the build script. |
| `packaging/make_icon.py` | Generates `packaging/app.ico` (brand teal `#00ABAF` badge + document glyph) entirely in code with Pillow — no committed binary icon. Consumed by both the spec (embedded in the EXE) and the installer (`SetupIconFile`). |
| `packaging/meeting_minutes.spec` | PyInstaller ONEDIR spec → `dist/MeetingMinutes/` (`MeetingMinutes.exe` + `_internal/`). Bundles `frontend/dist` → `frontend/dist` (bundle root, so `web.py`'s `parent.parent/frontend/dist` resolves) and the prebuilt `sample_arabic_minutes.docx` → `meeting_minutes/templates`. UPX disabled (trips AV); `console=False`. |
| `packaging/installer.iss` | Inno Setup 6 script. Per-user install (`PrivilegesRequired=lowest`, no admin/UAC), x64, Start Menu + optional Desktop shortcuts, fixed `AppId` GUID for clean upgrades. Outputs `../dist/installer/MeetingMinutes-Setup.exe`. |
| `packaging/build_windows.ps1` | One-shot **local** Windows build: frontend → isolated `.buildvenv` → install deps + PyInstaller → prebuild `.docx` template → `make_icon.py` → PyInstaller freeze → ISCC. Resolves the repo root itself, so cwd doesn't matter. |
| `.github/workflows/build-windows.yml` | **CI** build on `windows-latest`: same steps as the local script; installs Inno Setup via Chocolatey and invokes ISCC at `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`. Uploads the installer as an artifact (and attaches it to a GitHub Release on tag pushes). |

Build-time artifacts (not committed): `packaging/app.ico`, `frontend/dist/`,
`meeting_minutes/templates/sample_arabic_minutes.docx`, `.buildvenv/`,
`dist/MeetingMinutes/`, and `dist/installer/MeetingMinutes-Setup.exe`.

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

## End-user note

> **Meeting Minutes** is a small app that runs on your own PC.
>
> 1. Run **MeetingMinutes-Setup.exe** to install it (no admin rights needed).
> 2. Open it from the **Start Menu** (or the Desktop shortcut). Your browser
>    will open the app automatically, and a small teal icon appears near the
>    clock (the **system tray**).
> 3. When you're done, right-click that tray icon and choose **Quit**. Just
>    closing the browser tab does **not** close the app.
>
> No account, API key, or setup is required. If you also want to export minutes
> as **PDF**, ask your IT/admin to install **LibreOffice** — Word export works
> without it.
