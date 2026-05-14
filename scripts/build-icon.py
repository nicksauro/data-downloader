"""scripts/build-icon.py — Generate ``data_downloader.ico`` from Pillow primitives.

Owner: Uma (ux-design-expert) | v1.3.0 Wave 2D.

Builds a multi-resolution Windows ``.ico`` for the app installer, the
PyInstaller-bundled .exe, and the Qt ``QMainWindow`` window icon.

Why Pillow-only (not cairosvg)?
    The icon design is geometrically simple — a deep-navy rounded square
    background, a cyan/blue gradient candle body, a white wick, and a
    triangle arrowhead. Drawing this in Pillow keeps the build pipeline
    on a single, already-installed dependency (Pillow is transitively
    available via several dev tools and is the de-facto Python imaging
    lib). No SVG parser, no Cairo, no extra DLLs on the build host.

The SVG master at ``installer/assets/data_downloader.svg`` is kept as
the design-intent record for future refinements (e.g. swapping the
candle for a different symbol) and for designers who want to tweak
colors/shape in Inkscape/Illustrator. The .ico is the authoritative
artifact consumed by InnoSetup, PyInstaller, and Qt.

Outputs:
    - ``installer/assets/data_downloader.ico``  (multi-res: 16, 32, 48,
      64, 128, 256 — Windows Explorer + taskbar friendly)
    - ``src/data_downloader/ui/assets/icon.ico`` (copy — consumed by the
      PyInstaller spec template and ``MainWindow.setWindowIcon`` at
      runtime; spec datas() bundles ``ui/assets`` into ``_internal/assets``)

Run::

    python scripts/build-icon.py

Exit codes:
    0 — success (.ico written to both targets)
    1 — Pillow missing or write failure
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover — dev-only script
    print(f"[build-icon] Pillow not installed: {exc}", file=sys.stderr)
    print("[build-icon] Install via: pip install Pillow", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------------
# Paths
# ----------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_ICO = REPO_ROOT / "installer" / "assets" / "data_downloader.ico"
UI_ASSETS_ICO = REPO_ROOT / "src" / "data_downloader" / "ui" / "assets" / "icon.ico"

# ----------------------------------------------------------------------
# Palette — matches src/data_downloader/ui/assets/style.qss tokens
# ----------------------------------------------------------------------

BG_NAVY = (26, 31, 46, 255)  # #1A1F2E — surface.background
BODY_CYAN = (61, 208, 225, 255)  # #3DD0E1 — accent.cyan
BODY_BLUE = (79, 140, 255, 255)  # #4F8CFF — primary
WICK_WHITE = (232, 232, 234, 255)  # #E8E8EA — text.primary

# Resolutions emitted into the multi-res .ico.
ICON_SIZES = (16, 32, 48, 64, 128, 256)


# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------


_RGBA = tuple[int, int, int, int]


def _lerp_color(c1: _RGBA, c2: _RGBA, t: float) -> _RGBA:
    """Linear-interpolate two RGBA tuples by parameter ``t`` in [0, 1]."""
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
        int(c1[3] + (c2[3] - c1[3]) * t),
    )


def _draw_gradient_rect(
    img: Image.Image,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color_top: tuple[int, int, int, int],
    color_bottom: tuple[int, int, int, int],
) -> None:
    """Paint a vertical gradient rectangle on ``img`` (in-place).

    Used for the candle body — top is cyan (#3DD0E1), bottom is
    primary blue (#4F8CFF). Pillow doesn't ship a gradient primitive,
    so we draw row-by-row.
    """
    if y1 <= y0:
        return
    height = y1 - y0
    pixels = img.load()
    assert pixels is not None
    for y in range(y0, y1):
        t = (y - y0) / max(1, height - 1)
        color = _lerp_color(color_top, color_bottom, t)
        for x in range(x0, x1):
            pixels[x, y] = color


def _render_icon(size: int) -> Image.Image:
    """Render the icon at ``size``x``size``. Returns RGBA Pillow Image.

    Geometry is normalized as fractions of the canvas so every size
    looks pixel-tuned. At 16px the rounded corners flatten visually
    but the candle+arrow silhouette stays legible.
    """
    # Render at 4x then downsample for crisp anti-aliased edges (poor
    # man's MSAA — Pillow's DrawingContext has no built-in AA flag).
    scale = 4 if size <= 64 else 2
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background — rounded square deep-navy.
    radius = int(s * 0.11)
    draw.rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=BG_NAVY)

    # Geometry: candle body centered, wick above + arrow below.
    body_left = int(s * 0.3125)  # 80 / 256
    body_right = int(s * 0.6875)  # 176 / 256
    body_top = int(s * 0.3125)  # 80 / 256
    body_bottom = int(s * 0.703)  # 180 / 256

    wick_left = int(s * 0.484)  # 124 / 256
    wick_right = int(s * 0.516)  # 132 / 256
    wick_top = int(s * 0.156)  # 40 / 256
    wick_upper_bottom = body_top + 2  # overlap into body slightly
    wick_lower_top = body_bottom - 2
    wick_lower_bottom = int(s * 0.797)  # 204 / 256

    # Gradient body — cyan top → primary blue bottom.
    body_radius = max(1, int(s * 0.025))
    # Pre-fill the body area with the gradient, then mask to rounded rect.
    body_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    _draw_gradient_rect(
        body_layer, body_left, body_top, body_right, body_bottom, BODY_CYAN, BODY_BLUE
    )
    # Mask: rounded rect of the body.
    mask = Image.new("L", (s, s), 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.rounded_rectangle(
        (body_left, body_top, body_right - 1, body_bottom - 1),
        radius=body_radius,
        fill=255,
    )
    img.paste(body_layer, (0, 0), mask)

    # Wick — upper segment (above body).
    draw.rounded_rectangle(
        (wick_left, wick_top, wick_right - 1, wick_upper_bottom - 1),
        radius=max(1, int(s * 0.012)),
        fill=WICK_WHITE,
    )
    # Wick — lower segment (below body, into arrow shaft).
    draw.rounded_rectangle(
        (wick_left, wick_lower_top, wick_right - 1, wick_lower_bottom - 1),
        radius=max(1, int(s * 0.012)),
        fill=WICK_WHITE,
    )

    # Arrowhead — downward triangle replacing the bottom tip of the wick.
    arrow_left = int(s * 0.39)  # 100 / 256
    arrow_right = int(s * 0.61)  # 156 / 256
    arrow_top = wick_lower_bottom - 2
    arrow_bottom = int(s * 0.891)  # 228 / 256
    arrow_cx = (arrow_left + arrow_right) // 2
    draw.polygon(
        [(arrow_left, arrow_top), (arrow_right, arrow_top), (arrow_cx, arrow_bottom)],
        fill=WICK_WHITE,
    )

    # Downsample to target size with LANCZOS — smoothest for icons.
    if scale > 1:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def build_ico(target: Path) -> None:
    """Render every size in ``ICON_SIZES`` and save a multi-res .ico."""
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = [_render_icon(sz) for sz in ICON_SIZES]
    base = frames[-1]  # 256 — largest used as base; sizes= list embeds the rest
    base.save(
        target,
        format="ICO",
        sizes=[(sz, sz) for sz in ICON_SIZES],
    )


def main() -> int:
    try:
        build_ico(INSTALLER_ICO)
    except OSError as exc:
        print(f"[build-icon] Failed to write {INSTALLER_ICO}: {exc}", file=sys.stderr)
        return 1

    # Mirror to ui/assets/ so the spec template (and source-mode runtime)
    # can both pick it up via bundle_paths.asset_path().
    UI_ASSETS_ICO.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copyfile(INSTALLER_ICO, UI_ASSETS_ICO)
    except OSError as exc:
        print(f"[build-icon] Failed to copy to {UI_ASSETS_ICO}: {exc}", file=sys.stderr)
        return 1

    installer_kb = INSTALLER_ICO.stat().st_size / 1024
    ui_kb = UI_ASSETS_ICO.stat().st_size / 1024
    print(f"[build-icon] OK — {INSTALLER_ICO} ({installer_kb:.1f} KB)")
    print(f"[build-icon] OK — {UI_ASSETS_ICO} ({ui_kb:.1f} KB)")
    print(f"[build-icon] Sizes embedded: {', '.join(str(sz) for sz in ICON_SIZES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
