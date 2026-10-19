"""
Qt (PySide6) interface for the Logitech G102 / G203 Lightsync and Attack Shark X11.

Settings apply automatically: every change is written to config.json and pushed
to the mouse after a short pause. Run:  python main.py
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from string import Template

from PySide6.QtCore import (
    QByteArray,
    QEasingCurve,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from device_backend import BACKEND_LABELS, enumerate_devices, open_preferred
from hid_backend import BatteryInfo, DpiInfo, HidppError

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"

APP_VERSION = "1.4"
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "G102 Lightsync Control"

DPI_FLOOR = 50
DPI_CEILING = 26000
DPI_STEP = 50


def _data_dir() -> Path:
    """Writable directory for config.json (next to the script, or %APPDATA% when frozen)."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA") or Path.home())
        path = base / "G102 Lightsync Control"
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return path
    return ROOT


_config_override = os.environ.get("G102_CONFIG")
CONFIG_PATH = Path(_config_override) if _config_override else _data_dir() / "config.json"

DEFAULT_CONFIG = {
    "dpi": {
        "levels": [800, 1600, 3200],
        "active_level": 0,
    },
    "polling_rate": 1000,
    "lighting": {
        "mode": "static",
        "color": "#00E5A0",
        "brightness": 100,
        "speed": 60,
    },
    "app": {
        "autostart": False,
        "theme": "system",
        "last_device": "",
        "battery_notifications": True,
        "battery_threshold": 20,
    },
}

MODE_TO_LABEL = {
    "static": "Статичный",
    "breathing": "Дыхание",
    "cycle": "Цветовой цикл",
}
LABEL_TO_MODE = {label: mode for mode, label in MODE_TO_LABEL.items()}

MODE_HINT = {
    "static": "Горит выбранным цветом. Скорость не используется.",
    "breathing": "Плавно пульсирует выбранным цветом.",
    "cycle": "Переливается всеми цветами радуги — цвет не выбирается.",
}

THEME_TO_LABEL = {
    "system": "Системная",
    "light": "Светлая",
    "dark": "Тёмная",
}
LABEL_TO_THEME = {label: mode for mode, label in THEME_TO_LABEL.items()}

POLLING_RATES = [125, 250, 500, 1000]

COLOR_PRESETS = (
    "#2EE6A6", "#22D3EE", "#3B82F6", "#8B5CF6",
    "#F43F5E", "#F59E0B", "#FFFFFF", "#EF4444",
)

HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

ALL_FIELDS = frozenset({"dpi", "rate", "light"})

# --------------------------------------------------------------------- palette
LIGHT = {
    "SURFACE": "#F2F2F7",
    "RAISED": "#FFFFFF",
    "FIELD": "#F4F4F7",
    "HOVER": "#ECECF1",
    "SEPARATOR": "#DCDCE2",
    "BORDER": "#C9C9CF",
    "TEXT": "#1C1C1E",
    "TEXT_2": "#5F5F66",
    "TEXT_3": "#8E8E93",
    "ACCENT": "#067A52",
    "ACCENT_HOVER": "#056342",
    "ACCENT_TEXT": "#FFFFFF",
    "ACCENT_SOFT": "#E6F6EF",
    "ACCENT_BORDER": "#9FD8C3",
    "DANGER": "#C4121F",
    "WARNING": "#8A5300",
}

DARK = {
    "SURFACE": "#0E1116",
    "RAISED": "#171B22",
    "FIELD": "#11151B",
    "HOVER": "#232A33",
    "SEPARATOR": "#2A313B",
    "BORDER": "#343C48",
    "TEXT": "#F3F5F8",
    "TEXT_2": "#A6AFBD",
    "TEXT_3": "#6B7684",
    "ACCENT": "#3ADFA2",
    "ACCENT_HOVER": "#66ECBB",
    "ACCENT_TEXT": "#052015",
    "ACCENT_SOFT": "#122B21",
    "ACCENT_BORDER": "#1F5A44",
    "DANGER": "#FF6B7A",
    "WARNING": "#F2B04A",
}

THEMES = {"light": LIGHT, "dark": DARK}

QSS_TEMPLATE = Template(
    """
QWidget {
    color: $TEXT;
    font-family: "Segoe UI";
    font-size: 13px;
}
QMainWindow, QWidget#root {
    background: $SURFACE;
}
QWidget#header, QWidget#body, QWidget#inspector, QWidget#settingsContent {
    background: transparent;
}
QLabel {
    background: transparent;
}
QLabel#title {
    font-size: 22px;
    font-weight: bold;
    color: $TEXT;
}
QLabel#subtitle {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#status {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#status[tone="ok"] {
    color: $ACCENT;
}
QLabel#status[tone="busy"] {
    color: $WARNING;
}
QLabel#status[tone="error"] {
    color: $DANGER;
}
QLabel#sectionTitle {
    font-size: 14px;
    font-weight: bold;
}
QLabel#caption {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#cardTitle {
    font-size: 14px;
    font-weight: bold;
}
QLabel#deviceName {
    font-size: 17px;
    font-weight: bold;
}
QLabel#meta {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#metricLabel {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#metricBig {
    font-size: 26px;
    font-weight: bold;
}
QLabel#metric {
    font-size: 16px;
    font-weight: bold;
}
QLabel#metricText {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#fieldLabel {
    font-size: 13px;
    color: $TEXT_2;
}
QLabel#valueLabel {
    font-size: 13px;
    font-weight: bold;
}
QLabel#unit {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#hint {
    font-size: 12px;
    color: $TEXT_2;
}
QLabel#error {
    font-size: 12px;
    color: $DANGER;
}

QFrame#separator {
    background: $SEPARATOR;
    border: none;
}
QFrame#card {
    background: $RAISED;
    border: 1px solid $SEPARATOR;
    border-radius: 12px;
}
QFrame#dpiRow {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}
QFrame#dpiRow[active="true"] {
    background: $ACCENT_SOFT;
    border-color: $ACCENT_BORDER;
}
QFrame#activeBar {
    background: transparent;
    border-radius: 1px;
}
QFrame#activeBar[on="true"] {
    background: $ACCENT;
}

QPushButton {
    background: $FIELD;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 7px;
    padding: 5px 14px;
}
QPushButton:hover {
    background: $HOVER;
}
QPushButton:pressed {
    background: $SEPARATOR;
}
QPushButton#primary {
    background: $ACCENT;
    color: $ACCENT_TEXT;
    border: none;
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
}
QPushButton#primary:hover {
    background: $ACCENT_HOVER;
}
QPushButton#primary:disabled {
    background: $SEPARATOR;
    color: $TEXT_3;
}
QPushButton#secondary {
    background: transparent;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 6px 14px;
}
QPushButton#secondary:hover {
    background: $HOVER;
}
QPushButton#secondary:pressed {
    background: $SEPARATOR;
}
QPushButton#secondary:disabled {
    color: $TEXT_3;
    border-color: $SEPARATOR;
}
QPushButton#ghost {
    background: transparent;
    color: $TEXT_2;
    border: none;
    border-radius: 7px;
    padding: 5px 10px;
}
QPushButton#ghost:hover {
    background: $HOVER;
    color: $TEXT;
}
QPushButton#ghost:pressed {
    background: $SEPARATOR;
}
QPushButton#ghost:disabled {
    color: $TEXT_3;
    background: transparent;
}

QRadioButton {
    color: $TEXT_2;
    spacing: 8px;
    background: transparent;
}
QRadioButton[active="true"] {
    color: $TEXT;
}
QRadioButton::indicator {
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid $BORDER;
    background: $RAISED;
}
QRadioButton::indicator:hover {
    border-color: $ACCENT_BORDER;
}
QRadioButton::indicator:checked {
    background: $ACCENT;
    border: 3px solid $ACCENT_SOFT;
}

QCheckBox {
    color: $TEXT;
    spacing: 10px;
    background: transparent;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid $BORDER;
    background: $FIELD;
}
QCheckBox::indicator:hover {
    border-color: $ACCENT_BORDER;
}
QCheckBox::indicator:checked {
    background: $ACCENT;
    border-color: $ACCENT;
    image: url("$CHECK_ICON");
}

QSlider {
    background: transparent;
    min-height: 24px;
}
QSlider::groove:horizontal {
    height: 4px;
    background: $SEPARATOR;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: $ACCENT;
    border-radius: 2px;
}
QSlider::add-page:horizontal {
    background: $SEPARATOR;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: $ACCENT;
}
QSlider::handle:horizontal:hover,
QSlider::handle:horizontal:pressed {
    background: $ACCENT_HOVER;
}
QSlider[active="false"]::sub-page:horizontal,
QSlider[active="false"]::handle:horizontal {
    background: $ACCENT_BORDER;
}
QSlider[active="false"]::handle:horizontal:hover,
QSlider[active="false"]::handle:horizontal:pressed {
    background: $ACCENT;
}

QLineEdit {
    background: $FIELD;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: $ACCENT;
    selection-color: $ACCENT_TEXT;
}
QLineEdit:focus {
    border-color: $ACCENT;
}
QLineEdit[invalid="true"] {
    border-color: $DANGER;
}
QLineEdit#dpiEntry, QLineEdit#hexEntry {
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
}
QLineEdit#dpiEntry[active="true"] {
    color: $ACCENT;
    border-color: $ACCENT_BORDER;
}

QSpinBox {
    background: $FIELD;
    color: $TEXT;
    border: 1px solid $BORDER;
    border-radius: 6px;
    padding: 3px 6px;
    min-width: 64px;
}
QSpinBox:focus {
    border-color: $ACCENT;
}
QSpinBox:disabled {
    color: $TEXT_3;
    border-color: $BORDER;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px;
    background: transparent;
    border: none;
}

QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: $SEPARATOR;
    min-height: 32px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: $BORDER;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}
QScrollBar:horizontal {
    height: 0;
}

QPlainTextEdit#log {
    background: $FIELD;
    border: 1px solid $SEPARATOR;
    border-radius: 8px;
    padding: 8px;
    color: $TEXT_2;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
}

QMenuBar {
    background: $SURFACE;
    color: $TEXT;
    padding: 2px 6px;
}
QMenuBar::item {
    background: transparent;
    padding: 4px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected {
    background: $HOVER;
}
QMenuBar::item:pressed {
    background: $ACCENT_SOFT;
}
QMenu {
    background: $RAISED;
    border: 1px solid $BORDER;
    padding: 4px;
}
QMenu::item {
    background: transparent;
    padding: 6px 26px 6px 12px;
    border-radius: 6px;
}
QMenu::item:selected {
    background: $ACCENT_SOFT;
    color: $TEXT;
}
QMenu::item:disabled {
    color: $TEXT_3;
}
QMenu::separator {
    height: 1px;
    background: $SEPARATOR;
    margin: 4px 8px;
}

QToolTip {
    background: $RAISED;
    color: $TEXT;
    border: 1px solid $BORDER;
    padding: 4px 8px;
}
QMessageBox, QColorDialog {
    background: $RAISED;
}
QMessageBox QLabel {
    color: $TEXT;
}
"""
)


# ------------------------------------------------------------------- utilities
def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    amount = max(0.0, min(1.0, amount))
    return QColor.fromRgbF(
        first.redF() * (1 - amount) + second.redF() * amount,
        first.greenF() * (1 - amount) + second.greenF() * amount,
        first.blueF() * (1 - amount) + second.blueF() * amount,
    )


def _check_text_color(value: str) -> QColor:
    red, green, blue = hex_to_rgb(value)
    return QColor("#000000") if (red * 299 + green * 587 + blue * 114) / 1000 >= 150 else QColor("#FFFFFF")


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _palette(tokens: dict) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens["SURFACE"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens["TEXT"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens["FIELD"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens["RAISED"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens["TEXT"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens["RAISED"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens["TEXT"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["ACCENT"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens["ACCENT_TEXT"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens["RAISED"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tokens["TEXT"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens["TEXT_3"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(tokens["TEXT_3"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens["TEXT_3"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens["TEXT_3"]))
    return palette


def _system_is_dark() -> bool:
    override = os.environ.get("G102_THEME", "").strip().lower()
    if override in ("light", "dark"):
        return override == "dark"

    try:
        scheme = QGuiApplication.styleHints().colorScheme()
    except AttributeError:
        scheme = None
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False

    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
        except (OSError, ValueError):
            pass
    return False


def load_app_icon() -> QIcon:
    for name in ("app_icon.ico", "app_icon.png", "mouse.svg"):
        path = ASSETS / name
        if path.exists():
            return QIcon(str(path))
    return QIcon()


# --------------------------------------------------------------------- config
def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            config = _deep_merge(config, raw)
    except (OSError, ValueError):
        pass

    dpi = config.get("dpi")
    if not isinstance(dpi, dict):
        dpi = {}
        config["dpi"] = dpi
    levels = []
    raw_levels = dpi.get("levels")
    for value in raw_levels if isinstance(raw_levels, list) else []:
        try:
            levels.append(
                max(
                    DPI_FLOOR,
                    min(
                        DPI_CEILING,
                        int(round(int(value) / DPI_STEP) * DPI_STEP),
                    ),
                )
            )
        except (TypeError, ValueError):
            continue
    dpi["levels"] = levels or list(DEFAULT_CONFIG["dpi"]["levels"])
    try:
        active = int(dpi.get("active_level", 0))
    except (TypeError, ValueError):
        active = 0
    dpi["active_level"] = max(0, min(len(dpi["levels"]) - 1, active))

    try:
        rate = int(config.get("polling_rate", 1000))
    except (TypeError, ValueError):
        rate = 1000
    config["polling_rate"] = rate if rate in POLLING_RATES else 1000

    lighting = config.get("lighting")
    if not isinstance(lighting, dict):
        lighting = {}
        config["lighting"] = lighting
    if lighting.get("mode") not in MODE_TO_LABEL:
        lighting["mode"] = "static"
    color = str(lighting.get("color", "#00E5A0"))
    lighting["color"] = color.upper() if HEX_RE.match(color) else "#00E5A0"
    if not lighting["color"].startswith("#"):
        lighting["color"] = "#" + lighting["color"]
    for key, default in (("brightness", 100), ("speed", 60)):
        try:
            lighting[key] = max(1, min(100, int(lighting.get(key, default))))
        except (TypeError, ValueError):
            lighting[key] = default

    app_cfg = config.get("app")
    if not isinstance(app_cfg, dict):
        app_cfg = {}
        config["app"] = app_cfg
    app_cfg["autostart"] = bool(app_cfg.get("autostart", False))
    theme = str(app_cfg.get("theme", "system")).lower()
    app_cfg["theme"] = theme if theme in THEME_TO_LABEL else "system"
    device = str(app_cfg.get("last_device", "")).lower()
    app_cfg["last_device"] = device if device in BACKEND_LABELS else ""
    app_cfg["battery_notifications"] = bool(
        app_cfg.get("battery_notifications", True)
    )
    try:
        threshold = int(app_cfg.get("battery_threshold", 20))
    except (TypeError, ValueError):
        threshold = 20
    app_cfg["battery_threshold"] = max(5, min(50, threshold))

    return config


def save_config(config: dict) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


# ------------------------------------------------------------------ autostart
def startup_command() -> str:
    """Command Windows should run at login."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable)}"'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    if pythonw.exists():
        python = pythonw
    return f'"{python}" "{ROOT / "main.py"}"'


def read_autostart() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return str(value)
    except (FileNotFoundError, OSError):
        return None


def set_autostart(enabled: bool) -> None:
    """Create or remove the HKCU Run entry. Raises OSError on failure."""
    if sys.platform != "win32":
        raise OSError("Автозапуск поддерживается только в Windows.")
    import winreg

    if enabled:
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, startup_command())
    else:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, AUTOSTART_NAME)
        except FileNotFoundError:
            pass


def sync_autostart(enabled: bool) -> bool:
    """Make the registry match the setting. Returns True when something changed."""
    if sys.platform != "win32":
        return False
    current = read_autostart()
    command = startup_command() if enabled else None
    if current == command:
        return False
    set_autostart(enabled)
    return True


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


# ------------------------------------------------------------------- threading
class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(object)


class Worker(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self.function()
        except Exception as exc:  # noqa: BLE001 - reported to the UI
            self.signals.failed.emit(exc)
        else:
            self.signals.finished.emit(result)


# --------------------------------------------------------------------- widgets
class StatusDot(QWidget):
    """Small state dot with a halo pulse while work is in progress."""

    def __init__(self, tokens: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._tone = "idle"
        self._phase = 0.0
        self.setFixedSize(12, 12)
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def set_tokens(self, tokens: dict) -> None:
        self._tokens = tokens
        self.update()

    def set_tone(self, tone: str) -> None:
        self._tone = tone
        self._phase = 0.0
        if tone == "busy":
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.06) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        key = {"idle": "TEXT_2", "ok": "ACCENT", "busy": "WARNING", "error": "DANGER"}[self._tone]
        color = QColor(self._tokens[key])
        center = QPointF(self.width() / 2, self.height() / 2)

        if self._tone == "busy":
            halo = QColor(color)
            halo.setAlphaF(0.35 * (1.0 - self._phase))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(halo)
            radius = 3.0 + 3.4 * self._phase
            painter.drawEllipse(center, radius, radius)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(center, 3.4, 3.4)


class SegmentedControl(QWidget):
    """Equal-width segmented control with a sliding accent pill."""

    changed = Signal(str)

    def __init__(self, options: list[str], tokens: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._options = list(options)
        self._tokens = tokens
        self._index = 0
        self._position = 0.0
        self._hover = -1

        self._animation = QVariantAnimation(self)
        self._animation.setDuration(170)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_animation)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(34)
        self.setMaximumHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Выбор варианта")
        self.setAccessibleDescription("Стрелки влево и вправо переключают вариант")

    def sizeHint(self) -> QSize:
        return QSize(260, 34)

    def current_value(self) -> str | None:
        if not self._options:
            return None
        return self._options[self._index]

    def set_tokens(self, tokens: dict) -> None:
        self._tokens = tokens
        self.update()

    def set_value(self, value: str, notify: bool = False) -> None:
        try:
            index = self._options.index(value)
        except ValueError:
            return
        if index == self._index and not notify:
            return
        if notify and index == self._index:
            return
        self._animation.stop()
        self._index = index
        self._position = float(index)
        self.update()

    def _choose(self, index: int, notify: bool = True) -> None:
        if not 0 <= index < len(self._options) or index == self._index:
            return
        self._animation.stop()
        self._animation.setStartValue(float(self._position))
        self._animation.setEndValue(float(index))
        self._animation.start()
        self._index = index
        self.update()
        if notify:
            self.changed.emit(self._options[index])

    def _on_animation(self, value) -> None:
        self._position = float(value)
        self.update()

    def _index_at(self, x: float) -> int | None:
        if not self._options:
            return None
        width = max(1.0, self.width() - 6.0)
        segment = width / len(self._options)
        index = int((x - 3.0) / segment)
        return max(0, min(len(self._options) - 1, index))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(event.position().x())
            if index is not None:
                self.setFocus(Qt.FocusReason.MouseFocusReason)
                self._choose(index)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        index = self._index_at(event.position().x())
        if index != self._hover:
            self._hover = index if index != self._index else -1
            self.update()
        super().mouseMoveEvent(event)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._choose(self._index - 1)
            event.accept()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._choose(self._index + 1)
            event.accept()
            return
        if key == Qt.Key.Key_Home:
            self._choose(0)
            event.accept()
            return
        if key == Qt.Key.Key_End:
            self._choose(len(self._options) - 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event) -> None:
        if not self._options:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = self._tokens

        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor(tokens["SEPARATOR"]), 1))
        painter.setBrush(QColor(tokens["FIELD"]))
        painter.drawRoundedRect(track, 9, 9)

        inner = QRectF(3, 3, self.width() - 6, self.height() - 6)
        segment = inner.width() / len(self._options)

        if self._hover >= 0:
            hover = QRectF(
                inner.left() + self._hover * segment + 1,
                inner.top() + 1,
                segment - 2,
                inner.height() - 2,
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(tokens["HOVER"]))
            painter.drawRoundedRect(hover, 7, 7)

        pill = QRectF(
            inner.left() + self._position * segment + 1,
            inner.top() + 1,
            segment - 2,
            inner.height() - 2,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens["ACCENT"]))
        painter.drawRoundedRect(pill, 7, 7)

        font = QFont("Segoe UI")
        font.setPixelSize(13)
        font.setWeight(QFont.Weight.Medium)
        painter.setFont(font)

        for index, label in enumerate(self._options):
            influence = max(0.0, 1.0 - abs(self._position - index))
            painter.setPen(_mix(QColor(tokens["TEXT_2"]), QColor(tokens["ACCENT_TEXT"]), influence))
            rect = QRectF(inner.left() + index * segment, inner.top(), segment, inner.height())
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens["ACCENT_BORDER"]), 1.5))
            painter.drawRoundedRect(track.adjusted(1.5, 1.5, -1.5, -1.5), 7, 7)


class SwatchButton(QAbstractButton):
    """Round colour preset or the main rounded colour swatch."""

    def __init__(
        self,
        color: str,
        tokens: dict,
        *,
        size: int = 28,
        rounded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._color = QColor(color)
        self._selected = False
        self._rounded = rounded
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_tokens(self, tokens: dict) -> None:
        self._tokens = tokens
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_selected(self, selected: bool) -> None:
        if selected != self._selected:
            self._selected = selected
            self.update()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tokens = self._tokens

        rect = QRectF(3, 3, self.width() - 6, self.height() - 6)
        shape = QPainterPath()
        if self._rounded:
            shape.addRoundedRect(rect, 7, 7)
        else:
            shape.addEllipse(rect)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color)
        painter.drawPath(shape)

        if self._selected:
            border = QColor(tokens["ACCENT"])
        elif self.underMouse():
            border = QColor(tokens["ACCENT_BORDER"])
        else:
            border = QColor(tokens["BORDER"])
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border, 2))
        painter.drawPath(shape)

        if self._selected:
            check = QPen(_check_text_color(self._color.name()), 2.0)
            check.setCapStyle(Qt.PenCapStyle.RoundCap)
            check.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check)
            path = QPainterPath()
            path.moveTo(rect.left() + rect.width() * 0.28, rect.top() + rect.height() * 0.52)
            path.lineTo(rect.left() + rect.width() * 0.44, rect.top() + rect.height() * 0.68)
            path.lineTo(rect.left() + rect.width() * 0.74, rect.top() + rect.height() * 0.34)
            painter.drawPath(path)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens["ACCENT"]), 1.5))
            painter.drawEllipse(rect.adjusted(-2.5, -2.5, 2.5, 2.5))


class DeviceStage(QWidget):
    """The Lucide mouse glyph with a live preview of the lighting effect."""

    def __init__(self, tokens: dict, svg_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._svg_text = svg_text
        self._color = QColor("#00E5A0")
        self._mode = "static"
        self._brightness = 100
        self._speed = 60
        self._clock = time.monotonic()
        self._mask = self._render_mask(svg_text)

        self.setFixedSize(136, 168)
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)

    @staticmethod
    def _render_mask(svg_text: str) -> QImage | None:
        if not svg_text:
            return None
        svg = svg_text.replace("currentColor", "#FFFFFF")
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            return None
        size = 512
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()
        return image

    def set_tokens(self, tokens: dict) -> None:
        self._tokens = tokens
        self.update()

    def set_lighting(self, mode: str, color: QColor, brightness: int, speed: int) -> None:
        self._mode = mode
        self._color = QColor(color)
        self._brightness = max(1, min(100, int(brightness)))
        self._speed = max(1, min(100, int(speed)))
        self._clock = time.monotonic()
        self._update_timer()
        self.update()

    def _update_timer(self) -> None:
        if self._mode in ("breathing", "cycle") and self.isVisible():
            self._timer.start()
        else:
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._update_timer()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _level_and_color(self) -> tuple[float, QColor]:
        speed = self._speed / 100.0
        brightness = self._brightness / 100.0
        elapsed = time.monotonic() - self._clock

        if self._mode == "breathing":
            period = 4.2 - 3.0 * speed
            phase = 0.5 - 0.5 * math.cos(2 * math.pi * elapsed / max(0.4, period))
            return brightness * (0.22 + 0.78 * phase), self._color
        if self._mode == "cycle":
            period = 12.0 - 9.0 * speed
            hue = (elapsed / max(1.0, period)) % 1.0
            return brightness, QColor.fromHsvF(hue, 0.72, 1.0)
        return brightness, self._color

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        level, base = self._level_and_color()
        level = max(0.0, min(1.0, level))
        center = QPointF(self.width() / 2, 82)

        glow = QRadialGradient(center, 82)
        inner = QColor(base)
        inner.setAlpha(int(18 + 125 * level))
        middle = QColor(base)
        middle.setAlpha(int(6 + 52 * level))
        outer = QColor(base)
        outer.setAlpha(0)
        glow.setColorAt(0.0, inner)
        glow.setColorAt(0.45, middle)
        glow.setColorAt(1.0, outer)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(center, 82, 82)

        tint = QColor.fromRgbF(
            base.redF() * (0.32 + 0.68 * level),
            base.greenF() * (0.32 + 0.68 * level),
            base.blueF() * (0.32 + 0.68 * level),
        )

        box = 128.0
        glyph = QRectF((self.width() - box) / 2, 12, box, box)

        if self._mask is not None:
            ratio = self.devicePixelRatioF()
            pixmap = QPixmap(int(box * ratio), int(box * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            tint_painter = QPainter(pixmap)
            tint_painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            tint_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            tint_painter.drawImage(QRectF(0, 0, box, box), self._mask)
            tint_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            tint_painter.fillRect(QRectF(0, 0, box, box), tint)
            tint_painter.end()
            painter.drawPixmap(glyph.topLeft(), pixmap)
        else:
            # Fallback silhouette if the SVG asset is unavailable.
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(tint, 5))
            painter.drawRoundedRect(QRectF(center.x() - 26, 18, 52, 92), 26, 26)
            painter.drawLine(QPointF(center.x(), 30), QPointF(center.x(), 48))


# ------------------------------------------------------------------------ GUI
class App(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        self.mouse = None
        self.backend_key = ""
        self.max_levels = None
        self.dpi_min = DPI_FLOOR
        self.dpi_max = DPI_CEILING
        self.dpi_step = DPI_STEP
        self._settings = QSettings("G102 Lightsync Control", "G102 Lightsync Control")

        self._loading = True
        self._ready = False
        self._closing = False
        self._quitting = False
        self._applying = False
        self._apply_pending = False
        self._dirty: set[str] = set()
        self._palette_guard = False
        self._intro_started = False
        self._intro_animation: QPropertyAnimation | None = None
        self._tray_hint_shown = False
        self._workers: set[Worker] = set()
        self._last_product = ""
        self.dpi_rows: list[dict] = []
        self.preset_buttons: list[tuple[SwatchButton, str]] = []
        self.tray: QSystemTrayIcon | None = None
        self.tray_menu: QMenu | None = None
        self.tray_autostart_action: QAction | None = None
        self._narrow: bool | None = None

        self.active_index = int(self.cfg["dpi"]["active_level"])
        self.poll_rate = int(self.cfg["polling_rate"])
        self.mode = str(self.cfg["lighting"]["mode"])
        self.color_hex = str(self.cfg["lighting"]["color"])
        self.brightness = int(self.cfg["lighting"]["brightness"])
        self.speed = int(self.cfg["lighting"]["speed"])
        self.battery_notifications = bool(
            self.cfg.get("app", {}).get("battery_notifications", True)
        )
        self.battery_threshold = int(
            self.cfg.get("app", {}).get("battery_threshold", 20)
        )
        self._battery_warned = False

        self.tokens = LIGHT
        self.theme_name = "light"
        self.theme_mode = str(self.cfg.get("app", {}).get("theme", "system"))
        if self.theme_mode not in THEME_TO_LABEL:
            self.theme_mode = "system"

        try:
            self._svg_text = (ASSETS / "mouse.svg").read_text(encoding="utf-8")
        except OSError:
            self._svg_text = ""

        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)

        self._apply_timer = QTimer(self)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_now)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._persist)

        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._restore_status)

        self._battery_timer = QTimer(self)
        self._battery_timer.setInterval(60_000)
        self._battery_timer.timeout.connect(self._poll_battery)

        self.setWindowTitle("Lightsync Control")
        self.setWindowIcon(load_app_icon())
        self.setMinimumSize(420, 560)

        geometry = self._settings.value("window/geometry")
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(1120, 880)

        self._build_menu()
        self._build_ui()
        self._apply_theme()
        self._sync_stage()
        self._setup_tray()

        self._log("Поддерживаются Logitech G102/G203 Lightsync и Attack Shark X11.")
        self._log(
            "Для Logitech закройте G HUB: он занимает интерфейс HID++. "
            "Настройки применяются автоматически."
        )

        self._set_status("Не подключено", "idle")
        self._loading = False
        self._ready = True

        if os.environ.get("G102_NO_AUTOSTART_SYNC") != "1":
            QTimer.singleShot(0, self._sync_autostart_on_start)

        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(self._on_color_scheme_changed)
        app = QApplication.instance()
        if app is not None:
            app.paletteChanged.connect(self._on_palette_changed)

        QTimer.singleShot(320, self._auto_connect)

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        bar = self.menuBar()

        device = bar.addMenu("Устройство")
        connect_action = QAction("Подключить мышь", self)
        connect_action.setShortcut(QKeySequence("F5"))
        connect_action.triggered.connect(self.connect)
        device.addAction(connect_action)

        apply_action = QAction("Применить сейчас", self)
        apply_action.setShortcut(QKeySequence("Ctrl+Return"))
        apply_action.triggered.connect(self._manual_apply)
        device.addAction(apply_action)

        device.addSeparator()
        theme_menu = device.addMenu("Тема оформления")
        self.theme_actions: dict[str, QAction] = {}
        for mode, label in THEME_TO_LABEL.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode == self.theme_mode)
            action.triggered.connect(
                lambda _checked=False, chosen=mode: self._set_theme_mode(chosen)
            )
            theme_menu.addAction(action)
            self.theme_actions[mode] = action

        device.addSeparator()
        quit_action = QAction("Выход", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self._quit)
        device.addAction(quit_action)

        log_menu = bar.addMenu("Журнал")
        clear_action = QAction("Очистить журнал", self)
        clear_action.setShortcut(QKeySequence("Ctrl+L"))
        clear_action.triggered.connect(self._clear_log)
        log_menu.addAction(clear_action)

        help_menu = bar.addMenu("Справка")
        about_action = QAction("О программе", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    # ----------------------------------------------------------------- layout
    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("root")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(24, 12, 24, 16)
        outer.setSpacing(0)
        self.outer_layout = outer

        header = QWidget()
        header.setObjectName("header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setContentsMargins(0, 0, 0, 0)
        titles.setSpacing(1)
        title = QLabel("Lightsync Control")
        title.setObjectName("title")
        subtitle = QLabel(
            "Logitech G102 / G203 и Attack Shark X11  ·  настройки применяются автоматически"
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)
        self.header_subtitle = subtitle
        titles.addWidget(title)
        titles.addWidget(subtitle)
        header_layout.addLayout(titles, 1)

        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(8)
        self.status_dot = StatusDot(self.tokens)
        self.status_label = QLabel("Не подключено")
        self.status_label.setObjectName("status")
        status_layout.addWidget(self.status_dot)
        status_layout.addWidget(self.status_label)
        header_layout.addLayout(status_layout)

        outer.addWidget(header)
        outer.addSpacing(12)

        line = QFrame()
        line.setObjectName("separator")
        line.setFixedHeight(1)
        outer.addWidget(line)
        outer.addSpacing(14)

        body = QWidget()
        body.setObjectName("body")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(18)
        outer.addWidget(body, 1)
        self.body_layout = body_layout

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setMinimumWidth(430)
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.viewport().setStyleSheet("background: transparent;")

        content = QWidget()
        content.setObjectName("settingsContent")
        self.settings_layout = QVBoxLayout(content)
        self.settings_layout.setContentsMargins(0, 0, 8, 0)
        self.settings_layout.setSpacing(18)
        self.settings_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(content)
        body_layout.addWidget(self.scroll, 3)

        inspector = QWidget()
        inspector.setObjectName("inspector")
        inspector.setMinimumWidth(380)
        inspector_layout = QVBoxLayout(inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        inspector_layout.setSpacing(16)
        body_layout.addWidget(inspector, 2)
        self.inspector = inspector

        self._build_dpi_section(self.settings_layout)
        self._build_polling_section(self.settings_layout)
        self._build_lighting_section(self.settings_layout)
        self._build_app_section(self.settings_layout)
        self.settings_layout.addStretch(1)

        self._build_device_panel(inspector_layout)
        self._build_log_panel(inspector_layout)

        self._refresh_dpi_rows()
        self._update_remove_state()
        self._apply_responsive_layout(self.width())

    # ------------------------------------------------------------- responsive
    def _apply_responsive_layout(self, width: int) -> None:
        """Stack the settings and inspector vertically on narrow windows."""
        narrow = width < 980
        if narrow == self._narrow:
            return
        self._narrow = narrow

        direction = (
            QBoxLayout.Direction.TopToBottom
            if narrow
            else QBoxLayout.Direction.LeftToRight
        )
        self.body_layout.setDirection(direction)
        self.body_layout.setSpacing(12 if narrow else 18)

        margin = (14, 8, 14, 12) if narrow else (24, 12, 24, 16)
        self.outer_layout.setContentsMargins(*margin)
        self.scroll.setMinimumWidth(0 if narrow else 430)
        self.inspector.setMinimumWidth(0 if narrow else 380)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        if hasattr(self, "body_layout"):
            self._apply_responsive_layout(event.size().width())

    def _section(self, parent_layout: QVBoxLayout, title: str, caption: str | None = None) -> QFrame:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        if caption:
            description = QLabel(caption)
            description.setObjectName("caption")
            description.setWordWrap(True)
            layout.addWidget(description)

        card = QFrame()
        card.setObjectName("card")
        layout.addWidget(card)

        parent_layout.addWidget(container)
        return card

    # --------------------------------------------------------------------- DPI
    def _build_dpi_section(self, parent_layout: QVBoxLayout) -> None:
        card = self._section(
            parent_layout,
            "DPI",
            "Выберите активный уровень. Точное значение можно ввести в поле справа.",
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(6, 8, 6, 8)
        layout.setSpacing(0)

        self.dpi_box = QWidget()
        self.dpi_box_layout = QVBoxLayout(self.dpi_box)
        self.dpi_box_layout.setContentsMargins(0, 0, 0, 0)
        self.dpi_box_layout.setSpacing(2)
        layout.addWidget(self.dpi_box)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(8, 4, 8, 2)
        footer_layout.setSpacing(4)

        add_button = QPushButton("Добавить уровень")
        add_button.setObjectName("ghost")
        add_button.setAutoDefault(False)
        add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        add_button.setMinimumHeight(28)
        add_button.clicked.connect(self._add_level)
        footer_layout.addWidget(add_button)
        self.add_btn = add_button

        self.remove_btn = QPushButton("Удалить уровень")
        self.remove_btn.setObjectName("ghost")
        self.remove_btn.setAutoDefault(False)
        self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove_btn.setMinimumHeight(28)
        self.remove_btn.clicked.connect(self._remove_level)
        footer_layout.addWidget(self.remove_btn)
        footer_layout.addStretch(1)
        layout.addWidget(footer)

        self.radio_group = QButtonGroup(self)
        self.radio_group.setExclusive(True)

        for dpi in self.cfg["dpi"]["levels"]:
            self._add_dpi_row(int(dpi))

    def _add_dpi_row(self, dpi: int) -> None:
        index = len(self.dpi_rows)
        row = QFrame()
        row.setObjectName("dpiRow")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        indicator = QFrame()
        indicator.setObjectName("activeBar")
        indicator.setFixedSize(3, 18)

        radio = QRadioButton(f"Уровень {index + 1}")
        radio.setCursor(Qt.CursorShape.PointingHandCursor)
        self.radio_group.addButton(radio, index)
        radio.toggled.connect(
            lambda checked, i=index: self._on_active_dpi_change(i) if checked else None
        )

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(self.dpi_min, self.dpi_max)
        slider.setSingleStep(self.dpi_step)
        slider.setPageStep(max(self.dpi_step, 400))
        slider.setValue(self._clamp_dpi(dpi))
        slider.setMinimumWidth(90)
        slider.setFixedHeight(24)
        slider.valueChanged.connect(lambda value, i=index: self._on_dpi_slider(i, value))
        slider.sliderReleased.connect(self._commit_slider)

        entry = QLineEdit(str(self._clamp_dpi(dpi)))
        entry.setObjectName("dpiEntry")
        entry.setFixedSize(72, 28)
        entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        entry.setMaxLength(5)
        entry.editingFinished.connect(lambda i=index: self._commit_dpi_entry(i))

        unit = QLabel("DPI")
        unit.setObjectName("unit")
        unit.setFixedWidth(24)

        layout.addWidget(indicator)
        layout.addWidget(radio)
        layout.addWidget(slider, 1)
        layout.addWidget(entry)
        layout.addWidget(unit)

        self.dpi_box_layout.addWidget(row)
        self.dpi_rows.append(
            {
                "frame": row,
                "indicator": indicator,
                "radio": radio,
                "slider": slider,
                "entry": entry,
                "value": self._clamp_dpi(dpi),
            }
        )

        if index == self.active_index:
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)

    def _clamp_dpi(self, value: int) -> int:
        step = max(1, int(self.dpi_step or DPI_STEP))
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = self.dpi_min
        number = int(round(number / step) * step)
        return max(self.dpi_min, min(self.dpi_max, number))

    def _refresh_dpi_rows(self) -> None:
        for index, row in enumerate(self.dpi_rows):
            active = index == self.active_index
            row["frame"].setProperty("active", active)
            row["radio"].setProperty("active", active)
            row["entry"].setProperty("active", active)
            row["slider"].setProperty("active", active)
            row["indicator"].setProperty("on", active)
            for widget in (row["frame"], row["radio"], row["entry"], row["slider"], row["indicator"]):
                _repolish(widget)

    def _on_active_dpi_change(self, index: int) -> None:
        if self._loading:
            return
        self.active_index = max(0, min(len(self.dpi_rows) - 1, index))
        self._refresh_dpi_rows()
        self._persist()
        self._sync_stage()
        self._schedule_apply(140, "dpi")

    def _on_dpi_slider(self, index: int, value: int) -> None:
        if self._loading or index >= len(self.dpi_rows):
            return
        dpi = self._clamp_dpi(value)
        row = self.dpi_rows[index]
        if row["slider"].value() != dpi:
            row["slider"].blockSignals(True)
            row["slider"].setValue(dpi)
            row["slider"].blockSignals(False)
        row["value"] = dpi
        if not row["entry"].hasFocus():
            row["entry"].setText(str(dpi))
        self._sync_stage()
        self._schedule_save()
        self._schedule_apply(380, "dpi")

    def _commit_slider(self) -> None:
        if self._loading or not self._ready:
            return
        self._persist()
        self._apply_now()

    def _commit_dpi_entry(self, index: int) -> None:
        if self._loading or index >= len(self.dpi_rows):
            return
        row = self.dpi_rows[index]
        text = row["entry"].text().strip()
        try:
            value = int(text)
        except ValueError:
            self._log("DPI — целое число от 200 до 8000.")
            row["entry"].setText(str(row["value"]))
            return

        value = self._clamp_dpi(value)
        row["value"] = value
        row["slider"].blockSignals(True)
        row["slider"].setValue(value)
        row["slider"].blockSignals(False)
        row["entry"].setText(str(value))
        self._persist()
        self._sync_stage()
        self._dirty.add("dpi")
        self._apply_now()

    def _add_level(self) -> None:
        if self.max_levels is not None and len(self.dpi_rows) >= self.max_levels:
            self._log(
                f"Для этого устройства доступно не более {self.max_levels} уровней DPI."
            )
            return
        last = self.dpi_rows[-1]["value"] if self.dpi_rows else 800
        dpi = self._clamp_dpi(min(self.dpi_max, last + 800))
        self._add_dpi_row(dpi)
        self._refresh_dpi_rows()
        self._update_remove_state()
        self._persist()
        self._sync_stage()

    def _remove_level(self) -> None:
        if len(self.dpi_rows) <= 1:
            return
        row = self.dpi_rows.pop()
        self.dpi_box_layout.removeWidget(row["frame"])
        self.radio_group.removeButton(row["radio"])
        row["frame"].deleteLater()

        active_changed = self.active_index >= len(self.dpi_rows)
        if active_changed:
            self.active_index = len(self.dpi_rows) - 1
            radio = self.dpi_rows[self.active_index]["radio"]
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)

        self._refresh_dpi_rows()
        self._update_remove_state()
        self._persist()
        self._sync_stage()
        if active_changed:
            self._schedule_apply(140, "dpi")

    def _update_remove_state(self) -> None:
        self.remove_btn.setEnabled(len(self.dpi_rows) > 1)
        if hasattr(self, "add_btn"):
            self.add_btn.setEnabled(
                self.max_levels is None or len(self.dpi_rows) < self.max_levels
            )

    def _apply_device_limits(self, dpi: DpiInfo) -> None:
        """Adapt the DPI editors to the sensor range reported by the device."""
        minimum = max(DPI_FLOOR, int(getattr(dpi, "minimum", 0) or DPI_FLOOR))
        maximum = max(minimum, int(getattr(dpi, "maximum", 0) or DPI_CEILING))
        step = max(1, int(getattr(dpi, "step", 0) or DPI_STEP))

        changed = (minimum, maximum, step) != (self.dpi_min, self.dpi_max, self.dpi_step)
        self.dpi_min, self.dpi_max, self.dpi_step = minimum, maximum, step
        self.max_levels = getattr(self.mouse, "max_levels", None)

        for row in self.dpi_rows:
            value = self._clamp_dpi(row["value"])
            row["value"] = value
            slider = row["slider"]
            slider.blockSignals(True)
            slider.setRange(minimum, maximum)
            slider.setSingleStep(step)
            slider.setPageStep(max(step, (maximum - minimum) // 10 or step))
            slider.setValue(value)
            slider.blockSignals(False)
            row["entry"].setText(str(value))

        while self.max_levels is not None and len(self.dpi_rows) > self.max_levels:
            row = self.dpi_rows.pop()
            self.dpi_box_layout.removeWidget(row["frame"])
            self.radio_group.removeButton(row["radio"])
            row["frame"].deleteLater()

        self.active_index = max(0, min(len(self.dpi_rows) - 1, self.active_index))
        self._refresh_dpi_rows()
        self._update_remove_state()
        self._sync_stage()
        if changed:
            self._log(
                f"Диапазон DPI устройства: {minimum}–{maximum}, шаг {step}."
            )

    def _active_dpi(self) -> int:
        if not self.dpi_rows:
            return 800
        index = max(0, min(len(self.dpi_rows) - 1, self.active_index))
        return int(self.dpi_rows[index]["value"])

    # ------------------------------------------------------------- polling rate
    def _build_polling_section(self, parent_layout: QVBoxLayout) -> None:
        card = self._section(
            parent_layout,
            "Частота опроса",
            "Как часто мышь сообщает о движении. 1000 Гц — максимальная отзывчивость.",
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(0)

        self.poll_segment = SegmentedControl([f"{rate} Гц" for rate in POLLING_RATES], self.tokens)
        self.poll_segment.set_value(f"{self.poll_rate} Гц")
        self.poll_segment.changed.connect(self._on_polling)
        layout.addWidget(self.poll_segment)

    def _on_polling(self, label: str) -> None:
        if self._loading:
            return
        self.poll_rate = int(label.split()[0])
        self._persist()
        self._sync_stage()
        self._schedule_apply(140, "rate")

    # ---------------------------------------------------------------- lighting
    def _build_lighting_section(self, parent_layout: QVBoxLayout) -> None:
        card = self._section(parent_layout, "Подсветка", "Эффект и цвет подсветки корпуса.")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self.mode_segment = SegmentedControl(list(MODE_TO_LABEL.values()), self.tokens)
        self.mode_segment.set_value(MODE_TO_LABEL[self.mode])
        self.mode_segment.changed.connect(self._on_mode_change)
        layout.addWidget(self.mode_segment)

        self.mode_hint = QLabel(MODE_HINT[self.mode])
        self.mode_hint.setObjectName("hint")
        self.mode_hint.setWordWrap(True)
        layout.addWidget(self.mode_hint)

        self._build_color_block(layout)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(1, 100)
        self.brightness_slider.setValue(self.brightness)
        self.brightness_slider.setMinimumWidth(120)
        self.brightness_label = QLabel(f"{self.brightness}%")
        self.brightness_label.setObjectName("valueLabel")
        self.brightness_label.setFixedWidth(46)
        self.brightness_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.brightness_row = self._slider_row("Яркость", self.brightness_slider, self.brightness_label)
        layout.addWidget(self.brightness_row)

        self.speed_slider = QSlider(Qt.Orientation.Horizontal)
        self.speed_slider.setRange(1, 100)
        self.speed_slider.setValue(self.speed)
        self.speed_slider.setMinimumWidth(120)
        self.speed_label = QLabel(str(self.speed))
        self.speed_label.setObjectName("valueLabel")
        self.speed_label.setFixedWidth(46)
        self.speed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.speed_row = self._slider_row("Скорость", self.speed_slider, self.speed_label)
        layout.addWidget(self.speed_row)

        self.brightness_slider.valueChanged.connect(self._on_brightness)
        self.speed_slider.valueChanged.connect(self._on_speed)
        self.brightness_slider.sliderReleased.connect(self._commit_slider)
        self.speed_slider.sliderReleased.connect(self._commit_slider)

        self._sync_lighting_fields()

    def _build_color_block(self, layout: QVBoxLayout) -> None:
        self.color_block = QWidget()
        block = QVBoxLayout(self.color_block)
        block.setContentsMargins(0, 0, 0, 0)
        block.setSpacing(8)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel("Цвет")
        label.setObjectName("fieldLabel")
        label.setFixedWidth(64)
        row_layout.addWidget(label)

        self.color_swatch = SwatchButton(self.color_hex, self.tokens, size=32, rounded=True)
        self.color_swatch.setToolTip("Открыть палитру")
        self.color_swatch.setAccessibleName("Выбрать цвет подсветки")
        self.color_swatch.clicked.connect(self._pick_color)
        row_layout.addWidget(self.color_swatch)

        self.hex_entry = QLineEdit(self.color_hex)
        self.hex_entry.setObjectName("hexEntry")
        self.hex_entry.setFixedSize(104, 30)
        self.hex_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hex_entry.setMaxLength(7)
        self.hex_entry.editingFinished.connect(self._on_hex_enter)
        row_layout.addWidget(self.hex_entry)

        palette_button = QPushButton("Палитра…")
        palette_button.setObjectName("secondary")
        palette_button.setAutoDefault(False)
        palette_button.setCursor(Qt.CursorShape.PointingHandCursor)
        palette_button.setMinimumHeight(30)
        palette_button.clicked.connect(self._pick_color)
        row_layout.addWidget(palette_button)
        row_layout.addStretch(1)

        self.color_error = QLabel("")
        self.color_error.setObjectName("error")
        self.color_error.setWordWrap(True)
        self.color_error.hide()

        presets = QWidget()
        presets_layout = QHBoxLayout(presets)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(8)

        presets_label = QLabel("Пресеты")
        presets_label.setObjectName("fieldLabel")
        presets_label.setFixedWidth(64)
        presets_layout.addWidget(presets_label)

        for value in COLOR_PRESETS:
            swatch = SwatchButton(value, self.tokens, size=28)
            swatch.setToolTip(value)
            swatch.setAccessibleName(f"Пресет {value}")
            swatch.clicked.connect(lambda _checked=False, chosen=value: self._set_color(chosen))
            presets_layout.addWidget(swatch)
            self.preset_buttons.append((swatch, value))
        presets_layout.addStretch(1)

        block.addWidget(row)
        block.addWidget(self.color_error)
        block.addWidget(presets)
        layout.addWidget(self.color_block)
        self._refresh_presets()

    @staticmethod
    def _slider_row(label_text: str, slider: QSlider, value_label: QLabel) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        label = QLabel(label_text)
        label.setObjectName("fieldLabel")
        label.setFixedWidth(64)
        layout.addWidget(label)
        layout.addWidget(slider, 1)
        layout.addWidget(value_label)
        return row

    def _on_brightness(self, value: int) -> None:
        if self._loading:
            return
        self.brightness = int(value)
        self.brightness_label.setText(f"{value}%")
        self._sync_stage()
        self._schedule_save()
        self._schedule_apply(380, "light")

    def _on_speed(self, value: int) -> None:
        if self._loading:
            return
        self.speed = int(value)
        self.speed_label.setText(str(value))
        self._sync_stage()
        self._schedule_save()
        self._schedule_apply(380, "light")

    def _on_mode_change(self, label: str) -> None:
        if self._loading:
            return
        self.mode = LABEL_TO_MODE[label]
        self._sync_lighting_fields()
        self._persist()
        self._sync_stage()
        self._schedule_apply(140, "light")

    def _sync_lighting_fields(self) -> None:
        self.mode_hint.setText(MODE_HINT[self.mode])
        self.color_block.setVisible(self.mode != "cycle")
        self.speed_row.setVisible(self.mode != "static")
        if hasattr(self, "stage"):
            self._sync_stage()

    def _on_hex_enter(self) -> None:
        if self._loading:
            return
        value = self.hex_entry.text().strip().upper()
        if not HEX_RE.match(value):
            self.color_error.setText("Введите цвет в формате #RRGGBB.")
            self.color_error.show()
            self.hex_entry.setProperty("invalid", True)
            _repolish(self.hex_entry)
            return
        if not value.startswith("#"):
            value = "#" + value
        self._set_color(value)

    def _set_color(self, value: str) -> None:
        value = value.upper()
        self.color_hex = value
        self.color_error.setText("")
        self.color_error.hide()
        self.hex_entry.setProperty("invalid", False)
        _repolish(self.hex_entry)
        self.hex_entry.setText(value)
        self.color_swatch.set_color(value)
        self.color_swatch.setAccessibleName(f"Выбрать цвет подсветки, сейчас {value}")
        self.color_swatch.setToolTip(f"{value} — открыть палитру")
        self._refresh_presets()
        self._persist()
        self._sync_stage()
        self._schedule_apply(160, "light")

    def _refresh_presets(self) -> None:
        for swatch, preset in self.preset_buttons:
            swatch.set_selected(preset.upper() == self.color_hex.upper())

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self.color_hex), self, "Цвет подсветки")
        if chosen.isValid():
            self._set_color(chosen.name().upper())

    # ------------------------------------------------------------------ app
    def _build_app_section(self, parent_layout: QVBoxLayout) -> None:
        card = self._section(
            parent_layout,
            "Приложение",
            "Запуск вместе с Windows и поведение окна.",
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        self.autostart_check = QCheckBox("Запускать при входе в Windows")
        self.autostart_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autostart_check.setChecked(bool(self.cfg.get("app", {}).get("autostart", False)))
        self.autostart_check.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self.autostart_check)

        hint = QLabel(
            "При закрытии окна приложение остаётся в трее; выход — через меню иконки."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addSpacing(10)
        theme_label = QLabel("Тема оформления")
        theme_label.setObjectName("fieldLabel")
        layout.addWidget(theme_label)
        layout.addSpacing(4)

        self.theme_segment = SegmentedControl(
            list(THEME_TO_LABEL.values()), self.tokens
        )
        self.theme_segment.set_value(THEME_TO_LABEL[self.theme_mode])
        self.theme_segment.changed.connect(self._on_theme_segment)
        layout.addWidget(self.theme_segment)

        theme_hint = QLabel(
            "«Системная» следует за оформлением Windows. "
            "Светлую или тёмную можно выбрать вручную."
        )
        theme_hint.setObjectName("hint")
        theme_hint.setWordWrap(True)
        layout.addWidget(theme_hint)

        layout.addSpacing(12)
        battery_label = QLabel("Уведомления о заряде")
        battery_label.setObjectName("fieldLabel")
        layout.addWidget(battery_label)
        layout.addSpacing(4)

        self.battery_notify_check = QCheckBox("Предупреждать о низком заряде")
        self.battery_notify_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.battery_notify_check.setChecked(self.battery_notifications)
        self.battery_notify_check.toggled.connect(
            self._on_battery_notifications_toggled
        )
        layout.addWidget(self.battery_notify_check)

        threshold_row = QWidget()
        threshold_layout = QHBoxLayout(threshold_row)
        threshold_layout.setContentsMargins(0, 2, 0, 0)
        threshold_layout.setSpacing(8)
        threshold_label = QLabel("Порог уведомления")
        threshold_layout.addWidget(threshold_label)
        threshold_layout.addStretch(1)
        self.battery_threshold_spin = QSpinBox()
        self.battery_threshold_spin.setRange(5, 50)
        self.battery_threshold_spin.setSingleStep(5)
        self.battery_threshold_spin.setSuffix(" %")
        self.battery_threshold_spin.setValue(self.battery_threshold)
        self.battery_threshold_spin.setEnabled(self.battery_notifications)
        self.battery_threshold_spin.valueChanged.connect(
            self._on_battery_threshold_changed
        )
        threshold_layout.addWidget(self.battery_threshold_spin)
        layout.addWidget(threshold_row)

        battery_hint = QLabel(
            "Работает для Attack Shark X11: заряд показывается в карточке "
            "устройства, а при снижении до порога Windows один раз покажет "
            "нативное уведомление. После подзарядки выше порога оно включится снова."
        )
        battery_hint.setObjectName("hint")
        battery_hint.setWordWrap(True)
        layout.addWidget(battery_hint)

    def _on_battery_notifications_toggled(self, checked: bool) -> None:
        enabled = bool(checked)
        self.battery_notifications = enabled
        self._battery_warned = False
        if hasattr(self, "battery_threshold_spin"):
            self.battery_threshold_spin.setEnabled(enabled)
        if self._loading:
            return
        self._persist()
        self._log(
            "Уведомления о низком заряде включены."
            if enabled
            else "Уведомления о низком заряде выключены."
        )

    def _on_battery_threshold_changed(self, value: int) -> None:
        self.battery_threshold = int(value)
        self._battery_warned = False
        if self._loading:
            return
        self._save_timer.start(400)

    def _on_theme_segment(self, label: str) -> None:
        self._set_theme_mode(LABEL_TO_THEME.get(label, "system"))

    def _set_theme_mode(self, mode: str) -> None:
        if mode not in THEME_TO_LABEL:
            mode = "system"
        if mode == self.theme_mode:
            self._sync_theme_controls()
            return
        self.theme_mode = mode
        self._apply_theme()
        self._persist()
        self._log(f"Тема оформления: {THEME_TO_LABEL[mode].lower()}.")

    def _sync_theme_controls(self) -> None:
        label = THEME_TO_LABEL[self.theme_mode]
        if hasattr(self, "theme_segment"):
            self.theme_segment.set_value(label)
        for mode, action in getattr(self, "theme_actions", {}).items():
            action.blockSignals(True)
            action.setChecked(mode == self.theme_mode)
            action.blockSignals(False)

    def _on_autostart_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        enabled = bool(checked)
        try:
            set_autostart(enabled)
        except OSError as exc:
            self._log(f"Не удалось изменить автозапуск: {exc}")
            QMessageBox.warning(
                self,
                "Автозапуск",
                "Не удалось изменить настройку автозапуска.\n" + str(exc),
            )
            self._loading = True
            try:
                if hasattr(self, "autostart_check"):
                    self.autostart_check.setChecked(not enabled)
                if self.tray_autostart_action is not None:
                    self.tray_autostart_action.setChecked(not enabled)
            finally:
                self._loading = False
            return

        self.cfg.setdefault("app", {})["autostart"] = enabled
        self._loading = True
        try:
            if hasattr(self, "autostart_check"):
                self.autostart_check.setChecked(enabled)
            if self.tray_autostart_action is not None:
                self.tray_autostart_action.setChecked(enabled)
        finally:
            self._loading = False
        self._persist()
        self._log("Автозапуск включён." if enabled else "Автозапуск выключен.")

    def _sync_autostart_on_start(self) -> None:
        enabled = bool(self.cfg.get("app", {}).get("autostart", False))
        try:
            changed = sync_autostart(enabled)
        except OSError as exc:
            self._log(f"Не удалось обновить автозапуск: {exc}")
            return
        if changed:
            self._log(
                "Автозапуск обновлён для текущего расположения приложения."
                if enabled
                else "Запись автозапуска удалена."
            )

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._log("Область уведомлений недоступна: окно закрывается обычным образом.")
            return

        icon = self.windowIcon()
        if icon.isNull():
            icon = load_app_icon()
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("G102 Lightsync Control")

        menu = QMenu(self)
        show_action = menu.addAction("Открыть окно")
        show_action.triggered.connect(self._restore_window)
        menu.addSeparator()

        apply_action = menu.addAction("Применить сейчас")
        apply_action.triggered.connect(self._manual_apply)
        menu.addSeparator()

        autostart_action = menu.addAction("Запускать при входе в Windows")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(self.autostart_check.isChecked())
        autostart_action.toggled.connect(self._on_autostart_toggled)
        self.tray_autostart_action = autostart_action
        menu.addSeparator()

        quit_action = menu.addAction("Выход")
        quit_action.triggered.connect(self._quit)

        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(False)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_window()

    def _restore_window(self) -> None:
        self.setWindowOpacity(1.0)
        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ---------------------------------------------------------------- inspector
    def _build_device_panel(self, inspector_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)

        title = QLabel("Устройство")
        title.setObjectName("cardTitle")
        layout.addWidget(title)

        self.device_name_label = QLabel("Поиск устройства…")
        self.device_name_label.setObjectName("deviceName")
        self.device_name_label.setWordWrap(True)
        layout.addWidget(self.device_name_label)

        self.device_meta_label = QLabel("Подключение по USB HID")
        self.device_meta_label.setObjectName("meta")
        self.device_meta_label.setWordWrap(True)
        layout.addWidget(self.device_meta_label)
        layout.addSpacing(10)

        stage_row = QWidget()
        stage_layout = QHBoxLayout(stage_row)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(16)

        self.stage = DeviceStage(self.tokens, self._svg_text)
        stage_layout.addWidget(self.stage, 0, Qt.AlignmentFlag.AlignTop)

        readouts = QWidget()
        readout_layout = QVBoxLayout(readouts)
        readout_layout.setContentsMargins(0, 0, 0, 0)
        readout_layout.setSpacing(0)

        dpi_label = QLabel("Текущий DPI")
        dpi_label.setObjectName("metricLabel")
        readout_layout.addWidget(dpi_label)
        self.dpi_readout = QLabel("—")
        self.dpi_readout.setObjectName("metricBig")
        readout_layout.addWidget(self.dpi_readout)
        readout_layout.addSpacing(8)

        poll_label = QLabel("Частота опроса")
        poll_label.setObjectName("metricLabel")
        readout_layout.addWidget(poll_label)
        self.poll_readout = QLabel("—")
        self.poll_readout.setObjectName("metric")
        readout_layout.addWidget(self.poll_readout)
        readout_layout.addSpacing(8)

        light_label = QLabel("Подсветка")
        light_label.setObjectName("metricLabel")
        readout_layout.addWidget(light_label)
        self.light_readout = QLabel("—")
        self.light_readout.setObjectName("metricText")
        self.light_readout.setWordWrap(True)
        readout_layout.addWidget(self.light_readout)

        self.battery_box = QWidget()
        battery_layout = QVBoxLayout(self.battery_box)
        battery_layout.setContentsMargins(0, 8, 0, 0)
        battery_layout.setSpacing(0)
        battery_label = QLabel("Заряд батареи")
        battery_label.setObjectName("metricLabel")
        battery_layout.addWidget(battery_label)
        self.battery_readout = QLabel("—")
        self.battery_readout.setObjectName("metric")
        battery_layout.addWidget(self.battery_readout)
        self.battery_box.setVisible(False)
        readout_layout.addWidget(self.battery_box)

        readout_layout.addStretch(1)

        stage_layout.addWidget(readouts, 1)
        layout.addWidget(stage_row)
        layout.addSpacing(10)

        separator = QFrame()
        separator.setObjectName("separator")
        separator.setFixedHeight(1)
        layout.addWidget(separator)
        layout.addSpacing(10)

        self.connect_btn = QPushButton("Подключить мышь")
        self.connect_btn.setObjectName("secondary")
        self.connect_btn.setAutoDefault(False)
        self.connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.connect_btn.setMinimumHeight(34)
        self.connect_btn.clicked.connect(self.connect)
        layout.addWidget(self.connect_btn)

        inspector_layout.addWidget(card, 0)

    def _build_log_panel(self, inspector_layout: QVBoxLayout) -> None:
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        head = QWidget()
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(0, 0, 0, 0)
        head_layout.setSpacing(8)

        title = QLabel("Журнал")
        title.setObjectName("cardTitle")
        head_layout.addWidget(title)
        head_layout.addStretch(1)

        clear_button = QPushButton("Очистить")
        clear_button.setObjectName("ghost")
        clear_button.setAutoDefault(False)
        clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_button.setMinimumHeight(28)
        clear_button.clicked.connect(self._clear_log)
        head_layout.addWidget(clear_button)

        self.log_box = QPlainTextEdit()
        self.log_box.setObjectName("log")
        self.log_box.setReadOnly(True)
        self.log_box.setFrameShape(QFrame.Shape.NoFrame)
        self.log_box.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_box.document().setMaximumBlockCount(600)
        self.log_box.setMinimumHeight(120)

        layout.addWidget(head)
        layout.addWidget(self.log_box, 1)
        inspector_layout.addWidget(card, 1)

    # ------------------------------------------------------------ device stage
    def _sync_stage(self) -> None:
        if not hasattr(self, "stage"):
            return
        self.dpi_readout.setText(str(self._active_dpi()))
        self.poll_readout.setText(f"{self.poll_rate} Гц")
        if self.mode == "cycle":
            self.light_readout.setText(MODE_TO_LABEL[self.mode])
        else:
            self.light_readout.setText(f"{MODE_TO_LABEL[self.mode]} · {self.color_hex}")
        self.stage.set_lighting(
            self.mode,
            QColor(self.color_hex),
            int(self.brightness_slider.value()) if hasattr(self, "brightness_slider") else self.brightness,
            int(self.speed_slider.value()) if hasattr(self, "speed_slider") else self.speed,
        )

    # ------------------------------------------------------------------ theme
    def _apply_theme(self) -> None:
        if self.theme_mode == "dark":
            dark = True
        elif self.theme_mode == "light":
            dark = False
        else:
            dark = _system_is_dark()
        self.theme_name = "dark" if dark else "light"
        self.tokens = dict(THEMES[self.theme_name])
        check_name = "check_dark.svg" if self.theme_name == "dark" else "check_white.svg"
        self.tokens["CHECK_ICON"] = (ASSETS / check_name).as_posix()

        app = QApplication.instance()
        if app is not None:
            self._palette_guard = True
            try:
                app.setPalette(_palette(self.tokens))
                app.setStyleSheet(QSS_TEMPLATE.substitute(self.tokens))
            finally:
                self._palette_guard = False

        self.status_dot.set_tokens(self.tokens)
        self.poll_segment.set_tokens(self.tokens)
        self.mode_segment.set_tokens(self.tokens)
        if hasattr(self, "theme_segment"):
            self.theme_segment.set_tokens(self.tokens)
        self.color_swatch.set_tokens(self.tokens)
        for swatch, _preset in self.preset_buttons:
            swatch.set_tokens(self.tokens)
        self.stage.set_tokens(self.tokens)

        self._refresh_dpi_rows()
        self._sync_theme_controls()
        if self.isVisible():
            self._apply_dark_title_bar()
        self.update()

    def _on_color_scheme_changed(self, _scheme=None) -> None:
        if self.theme_mode == "system":
            self._apply_theme()

    def _on_palette_changed(self, _palette=None) -> None:
        if self._palette_guard or self.theme_mode != "system":
            return
        desired = "dark" if _system_is_dark() else "light"
        if desired != self.theme_name:
            QTimer.singleShot(0, self._apply_theme)

    def _apply_dark_title_bar(self) -> None:
        if sys.platform != "win32":
            return
        try:
            value = ctypes.c_int(1 if self.theme_name == "dark" else 0)
            handle = int(self.winId())
            for attribute in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    handle, attribute, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_dark_title_bar()
        if not self._intro_started:
            self._intro_started = True
            QTimer.singleShot(0, self._fade_in)

    def _fade_in(self) -> None:
        if (
            os.environ.get("G102_NO_INTRO") == "1"
            or QGuiApplication.platformName() == "offscreen"
        ):
            self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0.0)
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setDuration(200)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._intro_animation = animation
        animation.start()

    # ---------------------------------------------------------------- actions
    def connect(self) -> None:
        if self._closing:
            return
        self._battery_timer.stop()
        self._set_status("Подключение…", "busy")
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("Подключение…")
        self._run(
            self._connect_impl,
            on_success=self._after_connect,
            on_error=self._on_connect_error,
        )

    def _connect_impl(self):
        if self.mouse is not None:
            self.mouse.close()
            self.mouse = None
        preferred = self.cfg.get("app", {}).get("last_device") or None
        mouse = open_preferred(preferred)
        dpi = mouse.get_dpi_info()
        try:
            lighting = mouse.get_lighting_info()
        except HidppError:
            lighting = None
        try:
            rate = mouse.get_polling_rate()
        except HidppError:
            rate = 0
        try:
            onboard = mouse.get_onboard_mode()
        except HidppError:
            onboard = 0
        return mouse, dpi, lighting, rate, onboard

    def _after_connect(self, payload) -> None:
        mouse, dpi, lighting, rate, onboard = payload
        self.mouse = mouse
        self.backend_key = mouse.backend_key
        product = mouse.product or BACKEND_LABELS.get(
            self.backend_key, "Игровая мышь"
        )
        self._last_product = product
        pid = mouse.pid or 0
        connection = getattr(mouse, "connection_name", "")

        self._set_status(f"Подключено · {product}", "ok")
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Переподключить")
        self.device_name_label.setText(product)
        if self.tray is not None:
            self.tray.setToolTip(f"Lightsync Control · {product}")
        meta = [f"PID 0x{pid:04X}" + (f" · {connection}" if connection else "")]
        meta.append(f"Сенсор {dpi.minimum}–{dpi.maximum} DPI · шаг {dpi.step}")
        meta.append(f"На мыши: {dpi.current} DPI · {rate} Гц")
        self.device_meta_label.setText("\n".join(meta))
        self._log(
            f"Подключено: {product} (PID 0x{pid:04X}) · "
            f"{mouse.backend_name}"
        )
        self._log(f"DPI {dpi.minimum}–{dpi.maximum}, шаг {dpi.step}, текущий {dpi.current}")
        if self.backend_key == "attack_shark":
            self._log(
                "Подсветка Attack Shark: статичный / дыхание / неон, "
                "яркость 1–8, скорость 1–5."
            )
            if dpi.levels:
                self._log(
                    "Уровни DPI в профиле мыши: "
                    + ", ".join(str(value) for value in dpi.levels)
                )
            if not getattr(mouse, "wired", False):
                self._log(
                    "Заряд батареи обновляется по событиям мыши раз в минуту; "
                    "порог уведомления — в разделе «Приложение»."
                )
        elif lighting:
            effects = ", ".join(
                f"0x{effect_id:02X}→{index}"
                for effect_id, index in sorted(lighting.effects.items())
            )
            self._log(
                f"LED feature 0x{lighting.feature_id:04X} "
                f"(index 0x{lighting.feature_index:02X}), "
                f"кластеров {lighting.cluster_count}, эффекты: {effects or 'не обнаружены'}"
            )
        else:
            self._log("Подсветка Lightsync не обнаружена.")
        if onboard == 0x01:
            self._log(
                "Onboard-профиль включён — при применении настроек мышь "
                "переключится в host-режим (иначе polling rate не меняется)."
            )

        self._battery_timer.stop()
        self._battery_warned = False
        show_battery = self.backend_key == "attack_shark" and not getattr(
            mouse, "wired", False
        )
        if hasattr(self, "battery_box"):
            self.battery_readout.setText("—")
            self.battery_box.setVisible(show_battery)
        if show_battery:
            self._battery_timer.start()
            QTimer.singleShot(500, self._poll_battery)

        self._apply_device_limits(dpi)
        self.cfg.setdefault("app", {})["last_device"] = self.backend_key
        self._apply_pending = False
        self._dirty = set(ALL_FIELDS)
        self._apply_now()

    def _on_connect_error(self, _exc) -> None:
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("Подключить мышь")
        self._set_status("Не подключено", "error")
        self._battery_timer.stop()
        if hasattr(self, "battery_box"):
            self.battery_box.setVisible(False)

    # ---------------------------------------------------------------- battery
    def _poll_battery(self) -> None:
        if self._closing or self.mouse is None or self._applying:
            return
        if self.backend_key != "attack_shark":
            return
        if not getattr(self.mouse, "connected", True):
            return
        self._run(
            self.mouse.get_battery_info,
            on_success=self._on_battery,
            quiet=True,
        )

    def _on_battery(self, info: BatteryInfo | None) -> None:
        if self._closing or self.backend_key != "attack_shark":
            return
        if info is None:
            return
        status = ""
        if info.status == "charging":
            status = " · зарядка"
        elif info.status == "full":
            status = " · заряжено"
        if hasattr(self, "battery_readout"):
            self.battery_readout.setText(f"{info.percentage}%{status}")
            self.battery_box.setVisible(True)
        if self.tray is not None:
            self.tray.setToolTip(
                f"Lightsync Control · {self._last_product or 'мышь'} · "
                f"заряд {info.percentage}%"
            )
        self._maybe_notify_battery(info)

    def _maybe_notify_battery(self, info: BatteryInfo) -> None:
        threshold = int(self.battery_threshold)
        # Re-arm once the battery is clearly above the threshold or charging.
        if info.charging or info.full or info.percentage > min(100, threshold + 3):
            self._battery_warned = False
            return
        if not self.battery_notifications or self._battery_warned:
            return
        if info.percentage > threshold:
            return

        self._battery_warned = True
        product = self._last_product or "Attack Shark X11"
        message = (
            f"{product}: осталось {info.percentage}%. "
            "Пора поставить мышь на зарядку."
        )
        shown = False
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(
                "Низкий заряд мыши",
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                10_000,
            )
            shown = True
        self._log(
            f"Низкий заряд: {info.percentage}% (порог {threshold}%)."
            + (
                ""
                if shown
                else " Уведомление Windows недоступно — сообщение только в журнале."
            )
        )

    def _auto_connect(self) -> None:
        if self._closing or os.environ.get("G102_NO_AUTOCONNECT") == "1":
            return
        self._set_status("Поиск устройства…", "busy")
        self._run(
            enumerate_devices,
            on_success=self._on_enumerated,
            on_error=self._on_probe_error,
            quiet=True,
        )

    def _on_enumerated(self, devices) -> None:
        if not devices:
            self._log(
                "Поддерживаемые мыши не найдены. Подключите устройство "
                "и нажмите «Подключить мышь»."
            )
            self._set_status("Не подключено", "idle")
            return
        names = sorted({str(item.get("product")) for item in devices})
        self._log("Найдено: " + ", ".join(names))
        self.connect()

    def _on_probe_error(self, exc) -> None:
        self._log(f"Ошибка поиска: {exc}")
        self._set_status("Не подключено", "error")

    def _manual_apply(self) -> None:
        if self.mouse is None or not self.mouse.connected:
            self._log("Сначала подключите устройство.")
            return
        self._persist()
        self._dirty = set(ALL_FIELDS)
        self._apply_now()

    # ------------------------------------------------------------- auto-apply
    def _schedule_apply(self, delay: int = 360, field: str | None = None) -> None:
        if not self._ready or self._closing:
            return
        if field is not None:
            self._dirty.add(field)
        self._status_timer.stop()
        self._apply_timer.start(delay)

    def _schedule_save(self) -> None:
        if not self._ready or self._closing:
            return
        self._save_timer.start(300)

    def _apply_now(self) -> None:
        if self._closing or not self._ready:
            return
        self._apply_timer.stop()
        self._persist()

        if self.mouse is None or not self.mouse.connected:
            self._dirty.clear()
            return
        if self._applying:
            self._apply_pending = True
            return
        if not self._dirty:
            return
        self._start_apply()

    def _start_apply(self) -> None:
        fields = set(self._dirty)
        self._dirty.clear()
        settings = self._current_settings()
        self._applying = True
        self._apply_pending = False
        self._set_status("Применяется…", "busy")
        self._run(
            lambda: self._apply_all_impl(settings, fields),
            on_success=lambda _result: self._on_applied(),
            on_error=self._on_apply_error,
        )

    def _on_applied(self) -> None:
        self._applying = False
        self._set_status("Применено", "ok")
        self._status_timer.start(1500)

        if self._apply_pending:
            self._apply_pending = False
            QTimer.singleShot(60, self._apply_now)
        elif self._dirty and not self._apply_timer.isActive():
            QTimer.singleShot(60, self._apply_now)

    def _on_apply_error(self, exc) -> None:
        self._applying = False
        self._apply_pending = False
        self._dirty.clear()
        self._set_status("Ошибка применения", "error")
        if self.mouse is not None and self.mouse.connected:
            self._log(f"Ошибка применения: {exc}")
        else:
            self._log(f"Устройство отключилось: {exc}")

    def _restore_status(self) -> None:
        if self._applying or self._closing:
            return
        if self.mouse is not None and self.mouse.connected:
            product = (
                self._last_product
                or self.mouse.product
                or BACKEND_LABELS.get(self.backend_key, "Игровая мышь")
            )
            self._set_status(f"Подключено · {product}", "ok")
        else:
            self._set_status("Не подключено", "idle")

    def _current_settings(self) -> dict:
        """Snapshot widget values on the UI thread before any HID work starts."""
        return {
            "levels": [int(row["value"]) for row in self.dpi_rows],
            "dpi_index": max(
                0, min(len(self.dpi_rows) - 1, self.active_index)
            ),
            "dpi": self._active_dpi(),
            "rate": int(self.poll_rate),
            "mode": str(self.mode),
            "rgb": hex_to_rgb(self.color_hex),
            "brightness": int(self.brightness_slider.value()),
            "speed": int(self.speed_slider.value()),
        }

    def _apply_all_impl(self, settings: dict, fields: set[str]):
        if self.mouse is None:
            raise HidppError("Устройство не подключено.")
        if "dpi" in fields:
            self.mouse.apply_dpi(settings["levels"], settings["dpi_index"])
        if "rate" in fields:
            self.mouse.set_polling_rate(settings["rate"])
        if "light" in fields:
            self.mouse.set_lighting(
                settings["mode"],
                settings["rgb"],
                settings["brightness"],
                settings["speed"],
            )
        return tuple(sorted(fields))

    # ------------------------------------------------------------------ helpers
    def _run(self, function, on_success=None, on_error=None, quiet: bool = False) -> None:
        if self._closing:
            return
        worker = Worker(function)
        self._workers.add(worker)
        worker.signals.finished.connect(
            lambda result, w=worker: self._on_worker_done(w, result, on_success)
        )
        worker.signals.failed.connect(
            lambda exc, w=worker: self._on_worker_failed(w, exc, on_error, quiet)
        )
        self.pool.start(worker)

    def _on_worker_done(self, worker: Worker, result, callback) -> None:
        self._workers.discard(worker)
        if self._closing:
            return
        if callback is not None:
            callback(result)

    def _on_worker_failed(self, worker: Worker, exc, callback, quiet: bool) -> None:
        self._workers.discard(worker)
        if self._closing:
            return
        if not quiet:
            self._log(f"Ошибка: {exc}")
        if callback is not None:
            callback(exc)

    def _persist(self) -> None:
        if self._loading:
            return
        self.cfg = {
            "dpi": {
                "levels": [row["value"] for row in self.dpi_rows],
                "active_level": max(0, min(len(self.dpi_rows) - 1, self.active_index)),
            },
            "polling_rate": int(self.poll_rate),
            "lighting": {
                "mode": self.mode,
                "color": self.color_hex,
                "brightness": int(self.brightness_slider.value()),
                "speed": int(self.speed_slider.value()),
            },
            "app": {
                "autostart": bool(
                    self.autostart_check.isChecked()
                    if hasattr(self, "autostart_check")
                    else False
                ),
                "theme": self.theme_mode,
                "last_device": self.backend_key or self.cfg.get("app", {}).get("last_device", ""),
                "battery_notifications": bool(self.battery_notifications),
                "battery_threshold": int(self.battery_threshold),
            },
        }
        save_config(self.cfg)

    def _set_status(self, text: str, tone: str) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("tone", tone)
        _repolish(self.status_label)
        self.status_dot.set_tone(tone)

    def _show_about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("О программе")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(
            f"Lightsync Control {APP_VERSION}\n\n"
            "Неофициальная панель управления мышами Logitech G102 / G203 "
            "Lightsync (HID++ 2.0) и Attack Shark X11 (вендорный HID-протокол).\n"
            "Проект не связан с Logitech, Attack Shark и не одобрен ими.\n\n"
            "Протокол Attack Shark X11 основан на проекте\n"
            "github.com/HarukaYamamoto0/attack-shark-x11-driver.\n"
            "Иконка мыши: Lucide «mouse» (ISC)."
        )
        box.setIconPixmap(self.windowIcon().pixmap(64, 64))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _clear_log(self) -> None:
        self.log_box.clear()

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{timestamp}] {message}")
        bar = self.log_box.verticalScrollBar()
        bar.setValue(bar.maximum())

    def closeEvent(self, event) -> None:
        if (
            not self._quitting
            and self.tray is not None
            and self.tray.isVisible()
        ):
            event.ignore()
            if self._intro_animation is not None:
                self._intro_animation.stop()
            self.setWindowOpacity(1.0)
            self._persist()
            self._settings.setValue("window/geometry", self.saveGeometry())
            self._settings.sync()
            self.hide()
            if not self._tray_hint_shown:
                self._tray_hint_shown = True
                self.tray.showMessage(
                    "G102 Lightsync Control",
                    "Приложение свёрнуто в трей. Выход — через меню иконки.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
            return

        self._quitting = True
        self._closing = True
        self._apply_timer.stop()
        self._save_timer.stop()
        self._status_timer.stop()
        self._battery_timer.stop()
        if self._intro_animation is not None:
            self._intro_animation.stop()
        self._persist()

        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.sync()

        if self.tray is not None:
            self.tray.hide()

        self.pool.waitForDone(2500)
        if self.mouse is not None:
            try:
                self.mouse.close()
            except Exception:  # noqa: BLE001 - closing anyway
                pass
        super().closeEvent(event)


def run() -> int:
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "G102.Lightsync.Control"
            )
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("G102 Lightsync Control")
    app.setApplicationDisplayName("G102 Lightsync Control")
    app.setOrganizationName("G102 Lightsync Control")
    app.setStyle("Fusion")
    app.setWindowIcon(load_app_icon())

    window = App()
    window.show()
    return app.exec()
