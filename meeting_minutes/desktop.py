"""One-click desktop launcher for Meeting Minutes (frozen with PyInstaller).

Boots the FastAPI app on a free *local* port, waits until it answers, opens the
default browser at the app, and stays resident behind a system-tray icon whose
only real action is **Quit** (which stops the server cleanly). No console window,
no API key, no configuration — the app runs on the local Claude Code CLI / Cowork.

Design notes:
- This module imports cleanly on any OS: the tray deps (pystray/Pillow) and the
  server deps (uvicorn) are imported lazily, so the pure helpers below can be
  unit-tested on headless Linux/CI without a display or a running server.
- The server is bound to 127.0.0.1 only — never 0.0.0.0. The app has no auth and
  the only client is this machine's browser, so it must not be reachable on the LAN.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser

APP_NAME = "Meeting Minutes"
HOST = "127.0.0.1"  # local-only — see module docstring
HEALTH_PATH = "/api/health"
HAWAZ_TEAL = (0, 171, 175)  # #00ABAF — the brand teal already used in the .docx template
STARTUP_TIMEOUT_S = 30.0


def find_free_port(host: str = HOST) -> int:
    """Ask the OS for an unused TCP port on *host* and return it.

    There is a small TOCTOU window between closing the probe socket and uvicorn
    binding the port; on loopback for a single-user desktop app that is acceptable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def app_url(port: int, host: str = HOST) -> str:
    """The browser URL for the running app."""
    return f"http://{host}:{port}/"


def health_url(port: int, host: str = HOST) -> str:
    """The health-probe URL used to detect that the server is ready."""
    return f"http://{host}:{port}{HEALTH_PATH}"


def wait_for_health(url: str, *, timeout: float = STARTUP_TIMEOUT_S, interval: float = 0.25) -> bool:
    """Poll *url* until it returns HTTP 200, or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:  # noqa: S310 — fixed loopback URL
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass  # server not up yet — keep polling
        time.sleep(interval)
    return False


def _ensure_streams() -> None:
    """Frozen *windowed* apps run with ``sys.stdout``/``stderr`` set to ``None``;
    any ``print`` or uvicorn log write would then raise. Point them at a per-user
    log file so logging is safe and there is a trail to debug from."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    path = os.path.join(base, "MeetingMinutes", "app.log")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sink = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 — process-lifetime sink
    if sys.stdout is None:
        sys.stdout = sink
    if sys.stderr is None:
        sys.stderr = sink


def _fatal(message: str) -> None:
    """Surface a fatal startup error to a non-technical user (a Windows dialog when
    there is no console; stderr otherwise)."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)  # MB_ICONERROR
            return
    except Exception:
        pass
    print(f"{APP_NAME}: {message}", file=sys.stderr)


def _ensure_claude_runtime() -> None:
    """Make a Claude Code CLI available, preferring one the user already has.

    Order:
      1. If a real Claude Code **CLI** is already resolvable (on PATH or a known CLI
         install location — npm global, ~/.local/bin), use it and don't touch the
         environment. The Claude *desktop chat app* is deliberately NOT counted here:
         ClaudeCodeClient._resolve_binary skips it because it is a separate GUI product
         with no headless mode, so on a desktop-app-only machine we fall through to the
         bundled CLI instead of trying to drive the GUI as a CLI.
      2. Otherwise fall back to the portable Node.js + CLI we bundle in the
         installer (``vendor/node``): prepend its dir to PATH so the ``claude.cmd``
         shim finds node, and point CLAUDE_CODE_BIN at it.

    This means: installing a real Claude Code CLI later is automatically used, and a
    fresh PC with neither still works off the bundled copy. No-op in dev when
    nothing is bundled and no CLI is installed.
    """
    try:
        from meeting_minutes.llm import ClaudeCodeClient

        if ClaudeCodeClient._resolve_binary(None):
            return  # a real claude already exists — leave it alone
    except Exception:
        pass  # fall through to the bundled runtime

    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
    node_dir = os.path.join(base, "vendor", "node")
    if not os.path.isdir(node_dir):
        return  # nothing bundled (dev build) — leave resolution to the CLI
    # Bundled node.exe first on PATH so the claude.cmd shim resolves it.
    os.environ["PATH"] = node_dir + os.pathsep + os.environ.get("PATH", "")
    claude_cmd = os.path.join(node_dir, "claude.cmd")
    if os.path.isfile(claude_cmd):
        os.environ.setdefault("CLAUDE_CODE_BIN", claude_cmd)


def _launch_claude_login() -> None:
    """Open an interactive Claude Code session for the one-time browser login
    (delegates to the shared helper so the tray and the in-app button behave alike)."""
    try:
        from meeting_minutes.llm import launch_claude_login

        launch_claude_login()
    except Exception as exc:  # never crash the tray over a login attempt
        _fatal(f"Couldn't open the Claude login window.\n\n{exc}")


def build_server(port: int, host: str = HOST):
    """Construct a uvicorn server for the app that is safe to ``.run()`` in a thread.

    Returns a ``uvicorn.Server`` whose ``install_signal_handlers`` is a no-op
    (signal handlers can only be installed from the main thread) and which exposes
    ``.started`` / ``.should_exit`` for lifecycle control.
    """
    import uvicorn

    # Absolute (not relative) import on purpose: when frozen by PyInstaller this module
    # runs as the top-level script (__main__) with no parent package, so `from .web import
    # app` raises "attempted relative import with no parent package". The absolute form
    # works both frozen and when run as `python -m meeting_minutes.desktop`.
    from meeting_minutes.web import app

    class _ThreadedServer(uvicorn.Server):
        def install_signal_handlers(self) -> None:  # noqa: D401 — runs off the main thread
            return None

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    return _ThreadedServer(config)


def _tray_image():
    """A small round brand-teal icon for the system tray (generated, no asset file)."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=(*HAWAZ_TEAL, 255))
    return img


def _run_tray(server, url: str) -> None:
    """Block on a tray icon (Open / Quit). Falls back to a plain wait loop when
    pystray/Pillow are unavailable (headless CI, Linux dev)."""
    try:
        import pystray
    except Exception:
        _wait_until_exit(server)
        return

    def on_open(_icon, _item) -> None:
        webbrowser.open(url)

    def on_quit(icon, _item) -> None:
        server.should_exit = True
        icon.stop()

    def on_login(_icon, _item) -> None:
        _launch_claude_login()

    menu = pystray.Menu(
        pystray.MenuItem(f"Open {APP_NAME}", on_open, default=True),
        pystray.MenuItem("Log in to Claude", on_login),
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon(APP_NAME, _tray_image(), APP_NAME, menu)
    icon.run()  # blocks until on_quit calls icon.stop()


def _wait_until_exit(server) -> None:
    """Block until the server is asked to exit (no tray available)."""
    try:
        while not getattr(server, "should_exit", False):
            time.sleep(0.5)
    except KeyboardInterrupt:
        server.should_exit = True


def main() -> int:
    _ensure_streams()
    _ensure_claude_runtime()
    try:
        port = find_free_port()
        url = app_url(port)
        server = build_server(port)
        thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
        thread.start()

        if not wait_for_health(health_url(port)):
            server.should_exit = True
            _fatal(
                f"{APP_NAME} could not start its local service in time.\n\n"
                "Please try launching it again. If this keeps happening, restart your PC."
            )
            return 1

        webbrowser.open(url)
        _run_tray(server, url)  # blocks until the user quits

        server.should_exit = True
        thread.join(timeout=10)
        return 0
    except Exception as exc:  # never die silently in a windowed app
        _fatal(f"{APP_NAME} hit an unexpected error and must close.\n\n{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
