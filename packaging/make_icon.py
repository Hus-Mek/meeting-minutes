"""Generate the Windows application icon (packaging/app.ico) at build time.

This standalone Pillow script draws the MeetingMinutes app icon entirely in
code -- no external font or image files are required -- and writes it to
``app.ico`` next to this script. Keeping it generated (rather than committing a
binary .ico) means the icon can be regenerated/tweaked at any time and nothing
opaque lives in version control.

The resulting ``app.ico`` is consumed by:
  * the PyInstaller spec (packaging/meeting_minutes.spec) -> embeds it in
    MeetingMinutes.exe, and
  * the Inno Setup installer (packaging/installer.iss, SetupIconFile).

Run from anywhere -- the output path is resolved from ``__file__``, not cwd:

    python packaging/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

# --- Brand + canvas constants -------------------------------------------------

# Hawaz / MeetingMinutes brand teal.
BRAND_TEAL = (0, 171, 175, 255)  # #00ABAF
WHITE = (255, 255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)

# We draw once at the largest size, then downscale to every .ico member size.
# Working large keeps the rounded corners and glyph lines crisp when reduced.
BASE = 256

# .ico members written into the single multi-size file.
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _draw_icon(size: int) -> Image.Image:
    """Render the full icon (teal rounded-square badge + white document glyph).

    Everything is expressed as a fraction of ``size`` so the artwork scales
    cleanly to any working resolution.
    """
    img = Image.new("RGBA", (size, size), TRANSPARENT)
    draw = ImageDraw.Draw(img)

    # --- Teal rounded-square badge filling most of the canvas ----------------
    pad = round(size * 0.06)  # small breathing room from the edges
    radius = round(size * 0.22)  # generous, modern rounded corners
    draw.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=BRAND_TEAL,
    )

    # --- White "document" glyph centered on the badge ------------------------
    # A rounded white rectangle (the page).
    doc_w = round(size * 0.46)
    doc_h = round(size * 0.58)
    doc_x = (size - doc_w) // 2
    doc_y = (size - doc_h) // 2
    doc_radius = max(2, round(size * 0.04))
    draw.rounded_rectangle(
        (doc_x, doc_y, doc_x + doc_w, doc_y + doc_h),
        radius=doc_radius,
        fill=WHITE,
    )

    # Two short teal horizontal "text" lines across the page, upper third.
    line_h = max(1, round(size * 0.045))
    line_inset = round(doc_w * 0.18)  # left/right margin inside the page
    line_x0 = doc_x + line_inset
    line_x1 = doc_x + doc_w - line_inset
    line_radius = line_h // 2

    first_line_y = doc_y + round(doc_h * 0.26)
    gap = round(doc_h * 0.20)
    for i in range(2):
        ly = first_line_y + i * gap
        draw.rounded_rectangle(
            (line_x0, ly, line_x1, ly + line_h),
            radius=line_radius,
            fill=BRAND_TEAL,
        )

    return img


def make_icon() -> Path:
    """Build the multi-size .ico and return the path it was written to."""
    out_path = Path(__file__).resolve().parent / "app.ico"

    master = _draw_icon(BASE)

    # Pre-render each member with high-quality downscaling. Passing these as
    # ``append_images`` (plus the largest as the primary) embeds true,
    # individually-resized frames instead of letting Pillow guess.
    frames = [
        master.resize(sz, Image.LANCZOS) if sz != (BASE, BASE) else master
        for sz in ICON_SIZES
    ]
    primary = frames[-1]  # the 256x256 frame
    extras = frames[:-1]

    primary.save(
        out_path,
        format="ICO",
        sizes=ICON_SIZES,
        append_images=extras,
    )
    return out_path


if __name__ == "__main__":
    path = make_icon()
    print(path)
