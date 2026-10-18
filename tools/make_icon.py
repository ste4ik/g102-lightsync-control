"""Build the square app icon from the Lucide "mouse" SVG.

Run from the project root:

    python tools/make_icon.py

Outputs:
    assets/app_icon.png   512 x 512 (1:1)
    assets/app_icon.ico   multi-size Windows icon
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = ROOT / "assets" / "mouse.svg"
PNG_PATH = ROOT / "assets" / "app_icon.png"
ICO_PATH = ROOT / "assets" / "app_icon.ico"

SIZE = 512
RADIUS = 112
GLYPH_BOX = 316  # square area the 24-unit glyph is fitted into
MINT = QColor("#3ADFA2")


def render_glyph(svg_text: str) -> QImage:
    """Render the Lucide mouse glyph, mint on transparent."""
    svg = QByteArray(svg_text.replace("currentColor", MINT.name()).encode("utf-8"))
    renderer = QSvgRenderer(svg)
    image = QImage(GLYPH_BOX, GLYPH_BOX, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter)
    painter.end()
    return image


def build_icon(svg_text: str) -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # Squircle-ish tile, full bleed with a soft bottom tint.
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(0, 0, SIZE, SIZE), RADIUS, RADIUS)

    base = QLinearGradient(0, 0, SIZE, SIZE)
    base.setColorAt(0.0, QColor("#14543D"))
    base.setColorAt(0.55, QColor("#0B3B2B"))
    base.setColorAt(1.0, QColor("#05261B"))
    painter.fillPath(tile, base)

    # Mint glow behind the glyph.
    painter.save()
    painter.setClipPath(tile)
    glow = QRadialGradient(SIZE / 2, SIZE / 2 - 12, SIZE * 0.46)
    glow.setColorAt(0.0, QColor(58, 223, 162, 92))
    glow.setColorAt(0.55, QColor(58, 223, 162, 30))
    glow.setColorAt(1.0, QColor(58, 223, 162, 0))
    painter.fillRect(QRectF(0, 0, SIZE, SIZE), glow)
    painter.restore()

    # Hairline inner edge keeps the tile crisp on light backgrounds.
    painter.setPen(QPen(QColor(255, 255, 255, 26), 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(1, 1, SIZE - 2, SIZE - 2), RADIUS - 1, RADIUS - 1)

    glyph = render_glyph(svg_text)
    painter.drawImage(
        QRectF((SIZE - GLYPH_BOX) / 2, (SIZE - GLYPH_BOX) / 2, GLYPH_BOX, GLYPH_BOX),
        glyph,
    )
    painter.end()
    return image


def main() -> int:
    if not SVG_PATH.exists():
        print(f"Missing {SVG_PATH}", file=sys.stderr)
        return 1

    _app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    svg_text = SVG_PATH.read_text(encoding="utf-8")

    icon = build_icon(svg_text)
    if not icon.save(str(PNG_PATH), "PNG"):
        print(f"Could not write {PNG_PATH}", file=sys.stderr)
        return 1

    with Image.open(PNG_PATH) as source:
        source.save(
            ICO_PATH,
            format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )

    print(f"Wrote {PNG_PATH.relative_to(ROOT)} ({icon.width()}x{icon.height()})")
    print(f"Wrote {ICO_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
