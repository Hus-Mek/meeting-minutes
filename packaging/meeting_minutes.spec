# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the MeetingMinutes Windows desktop app (ONEDIR).

Build layout
------------
This is a ONEDIR build:

    Analysis  ->  PYZ  ->  EXE(exclude_binaries=True)  ->  COLLECT

COLLECT is named "MeetingMinutes", so the output tree is::

    dist/MeetingMinutes/
        MeetingMinutes.exe      <- windowed (no console) launcher
        _internal/              <- Python runtime, deps, and bundled data

The Inno Setup installer (packaging/installer.iss) ships this whole
``dist\\MeetingMinutes\\*`` tree recursively.

Why the data dest paths are EXACTLY these
-----------------------------------------
The freeze entry point is ``meeting_minutes/desktop.py``, whose ``main()``
lazily does ``from .web import app``. Inside ``meeting_minutes/web.py`` the
React SPA directory is resolved as::

    _DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

In the frozen app the bundled source lives at ``meeting_minutes/web.py``, so
``Path(__file__).resolve().parent.parent`` is the BUNDLE ROOT. That means
``frontend/dist`` must sit at the bundle root for the SPA to be found — hence
the dest ``"frontend/dist"`` below (NOT under ``meeting_minutes/``).

Similarly the .docx minutes template is PREBUILT at packaging time and bundled
to ``meeting_minutes/templates`` so the frozen app never has to write the
template into read-only ``Program Files`` at runtime.

UPX is disabled everywhere: compressed binaries frequently trip antivirus
heuristics on Windows, which is unacceptable for a non-technical end user.
"""

import os

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# SPECPATH is injected by PyInstaller and points at the packaging/ directory
# (where this .spec lives). ROOT is therefore the repo root. Every path below
# is built ABSOLUTELY from ROOT so the build works no matter which cwd
# PyInstaller is invoked from.
ROOT = os.path.dirname(SPECPATH)

# --- Bundled data files -----------------------------------------------------
# See the module docstring for the parent.parent _DIST rationale behind these
# exact dest paths.
datas = [
    # React SPA -> bundle root, so web.py's _DIST (parent.parent/frontend/dist)
    # resolves correctly inside the frozen app.
    (os.path.join(ROOT, "frontend", "dist"), "frontend/dist"),
    # Prebuilt Arabic minutes template -> meeting_minutes/templates, so the
    # frozen app reads it from the bundle instead of writing into Program Files.
    (
        os.path.join(ROOT, "meeting_minutes", "templates", "sample_arabic_minutes.docx"),
        "meeting_minutes/templates",
    ),
]
# python-docx ("docx") and docxtpl ship their own data files (e.g. the default
# .docx templates / XML parts) that PyInstaller won't pick up automatically.
datas += collect_data_files("docx")
datas += collect_data_files("docxtpl")

# Bundle a portable Node.js + the Claude Code CLI when present. CI vendors these
# into vendor/node BEFORE the build (download Node, then
# `npm i -g @anthropic-ai/claude-code --prefix vendor/node`), so the frozen app
# ships everything it needs except a one-time Claude login. The launcher prefers a
# claude the user already has and only falls back to this. Guarded so dev/local
# builds without the vendor dir still work.
_vendor_node = os.path.join(ROOT, "vendor", "node")
if os.path.isdir(_vendor_node):
    datas.append((_vendor_node, "vendor/node"))

# --- Hidden imports ---------------------------------------------------------
# uvicorn and pystray load their concrete implementations dynamically (by
# string), so PyInstaller's static analysis misses them — collect every
# submodule. web / readai_web are imported lazily from desktop.main(), so name
# them explicitly to guarantee they're frozen in.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("pystray")
    + ["meeting_minutes.web", "meeting_minutes.readai_web"]
)

# --- Excludes ---------------------------------------------------------------
# None of these are needed at runtime. Excluding them trims the bundle size and
# avoids pulling in the stdlib GUI stack (tkinter) and heavy scientific deps.
# pytest / _pytest are only declared in requirements.txt for the test suite.
excludes = [
    "tkinter",
    "matplotlib",
    "numpy",
    "pandas",
    "pytest",
    "_pytest",
]

a = Analysis(
    scripts=[os.path.join(ROOT, "meeting_minutes", "desktop.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # ONEDIR: binaries live in _internal/, collected below
    name="MeetingMinutes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trips antivirus on Windows
    console=False,  # windowed app: no console window
    disable_windowed_traceback=False,
    icon=os.path.join(SPECPATH, "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,  # UPX trips antivirus on Windows
    name="MeetingMinutes",
)
