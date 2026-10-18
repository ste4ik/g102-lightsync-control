# Icon assets

## `mouse.svg`

- Icon: **Lucide "mouse"**
- Version: `lucide-static@0.523.0`
- Source: <https://lucide.dev/icons/mouse>
- Downloaded from: <https://cdn.jsdelivr.net/npm/lucide-static@0.523.0/icons/mouse.svg>
- License: **ISC** — the copyright and permission notice is kept in the SVG header.
  Lucide's license: <https://lucide.dev/license.md>

## `app_icon.png`, `app_icon.ico`

Generated from `mouse.svg` by `tools/make_icon.py`.

- `app_icon.png` — 512 × 512 (1:1)
- `app_icon.ico` — multi-size Windows icon (16, 24, 32, 48, 64, 128, 256)

To regenerate: `python -m pip install Pillow PySide6-Essentials`, then
`python tools/make_icon.py` from the project root.

The icon is a dark green rounded square with the Lucide mouse glyph and a mint
glow. The same SVG is rendered by the device preview in the app.
