"""
Unified device layer: picks whichever supported mouse is connected.

Both backends expose the same small interface used by the GUI:

    open(path=None) / close() / connected / product / pid / backend_key
    get_dpi_info() / apply_dpi(levels, active_index)
    get_polling_rate() / set_polling_rate(hz)
    get_lighting_info() / set_lighting(mode, rgb, brightness, speed)
    get_onboard_mode()
    get_battery_info()

The Attack Shark X11 backend also implements set_dpi() for convenience.
get_battery_info() returns a BatteryInfo for wireless mice and None for
wired devices (the G102/G203 has no battery).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from attack_shark_backend import AttackSharkX11
from hid_backend import G102Mouse, HidppError

BACKEND_CLASSES = {
    "logitech": G102Mouse,
    "attack_shark": AttackSharkX11,
}

BACKEND_LABELS = {
    "logitech": "Logitech G102 / G203 Lightsync",
    "attack_shark": "Attack Shark X11",
}


def enumerate_devices() -> List[Dict[str, object]]:
    """Return one entry per physical mouse found (best effort)."""
    found: List[Dict[str, object]] = []
    for key, backend in BACKEND_CLASSES.items():
        try:
            items = backend.enumerate()
        except Exception:  # noqa: BLE001 - enumeration must never break the UI
            continue
        seen = set()
        for item in items:
            product_id = item.get("product_id")
            product = item.get("product_string") or BACKEND_LABELS[key]
            # The Logitech backend exposes several collections of one mouse;
            # collapse them by product id + product string.
            identity = (key, product_id, product)
            if identity in seen:
                continue
            seen.add(identity)
            found.append(
                {
                    "backend": key,
                    "vendor_id": item.get("vendor_id"),
                    "product_id": product_id,
                    "product": product,
                }
            )
    return found


def _order(preferred_backend: Optional[str]) -> List[str]:
    order = [key for key in BACKEND_CLASSES if key == preferred_backend]
    order.extend(key for key in BACKEND_CLASSES if key != preferred_backend)
    return order


def open_preferred(preferred_backend: Optional[str] = None):
    """Open the first available supported mouse and return the backend instance."""
    errors: List[str] = []
    for key in _order(preferred_backend):
        backend = BACKEND_CLASSES[key]
        try:
            if not backend.enumerate():
                continue
        except Exception:  # noqa: BLE001 - try the next backend
            continue
        mouse = backend()
        try:
            mouse.open()
        except HidppError as exc:
            errors.append(f"{BACKEND_LABELS[key]}: {exc}")
            try:
                mouse.close()
            except Exception:
                pass
            continue
        return mouse

    if errors:
        raise HidppError("Не удалось подключить устройство. " + " | ".join(errors))
    raise HidppError(
        "Поддерживаемые мыши не найдены (Logitech G102/G203 или Attack Shark X11)."
    )


def diagnostic() -> None:
    """Print what is connected: python device_backend.py"""
    devices = enumerate_devices()
    if not devices:
        print("Поддерживаемые устройства не найдены.")
        return
    for item in devices:
        print(
            f"{BACKEND_LABELS[item['backend']]}: "
            f"PID=0x{int(item['product_id'] or 0):04X} · {item['product']}"
        )


if __name__ == "__main__":
    diagnostic()
