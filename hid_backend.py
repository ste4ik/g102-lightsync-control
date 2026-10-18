"""
HID++ 2.0 backend for Logitech G102 / G203 Lightsync.

Only HID++ feature reports are used (no custom drivers, no libusb replacement).
Protocol references:
  * HID++ 2.0 long report: report ID 0x11, device index 0xFF for wired devices.
  * USB transport: HID output report 0x11 (hidapi write) and input report
    0x11 (hidapi read). Feature reports are NOT used on this device.
  * Feature discovery through IRoot (feature index 0x00, function 0x00).
  * 0x2201 AdjustableDpi       - sensor count / DPI list / get / set
  * 0x8060 AdjustableReportRate - list / get / set (rate is encoded in ms)
  * 0x8071 RGB Effects          - clusters + effects (G102/G203 Lightsync)
  * 0x8070 Color LED Effects    - legacy fallback

The function byte of a HID++ request is (function << 4) | software_id.
Logitech's own tooling and the well-known g203-led implementation use
software id 0x0B, so this backend does the same.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import hid
except ImportError as exc:  # pragma: no cover - only hit before pip install
    raise ImportError(
        "Не найден модуль hid. Установите зависимости: pip install -r requirements.txt"
    ) from exc


VENDOR_ID = 0x046D

# Product IDs that use the same HID++ Lightsync protocol.
SUPPORTED_PIDS = {
    0xC092: "G102 / G203 Lightsync",
    0xC093: "G102 Lightsync",
    0xC09D: "G203 Lightsync",
    0xC084: "G203 Prodigy",
}

HIDPP_USAGE_PAGE = 0xFF00
REPORT_ID = 0x11          # 20-byte long report
DEVICE_INDEX = 0xFF       # wired / directly connected device
SOFTWARE_ID = 0x0B

FEATURE_IRoot = 0x0000
FEATURE_DPI = 0x2201
FEATURE_REPORT_RATE = 0x8060
FEATURE_RGB_EFFECTS = 0x8071
FEATURE_COLOR_LED_EFFECTS = 0x8070
FEATURE_ONBOARD_PROFILES = 0x8100

# Effect IDs returned by getEffectInfo (0x8071).
EFFECT_IDS = {
    "static": 0x01,
    "cycle": 0x03,
    "wave": 0x04,
    "breathing": 0x0A,
}

# Cluster effect indices used by G102/G203 Lightsync.
# Needed only if effect discovery is not available.
DEFAULT_EFFECT_INDEX = {
    "static": 1,
    "cycle": 2,
    "wave": 3,
    "breathing": 4,
}

# HID++ "software control" switch: take the LEDs away from the onboard profile.
RGB_SW_CONTROL_PRELUDE = bytes((0x01, 0x03, 0x05))

POLLING_MS = {1000: 1, 500: 2, 250: 4, 125: 8}


class HidppError(RuntimeError):
    """Raised when the device rejects a HID++ request."""


def _be16(data: bytes, offset: int = 0) -> int:
    return (data[offset] << 8) | data[offset + 1]


@dataclass
class DpiInfo:
    sensor_count: int
    minimum: int
    maximum: int
    step: int
    current: int
    default: int = 0
    levels: List[int] = field(default_factory=list)


@dataclass
class LightingInfo:
    feature_id: int          # protocol ID: 0x8071 or 0x8070
    feature_index: int       # runtime index used in HID++ reports
    cluster_count: int
    effects: Dict[int, int]  # effect_id -> cluster effect index


class G102Mouse:
    """Small, thread-safe HID++ 2.0 client."""

    def __init__(self) -> None:
        self._dev = None
        self._lock = threading.RLock()
        self._feature_cache: Dict[int, int] = {}
        self.pid: Optional[int] = None
        self.product = ""
        self.path = None

    # ------------------------------------------------------------------ device
    @staticmethod
    def enumerate() -> List[dict]:
        """Return the vendor-defined HID++ collections of supported mice."""
        result: List[dict] = []
        for info in hid.enumerate(VENDOR_ID, 0):
            if info.get("product_id") not in SUPPORTED_PIDS:
                continue
            if info.get("usage_page") != HIDPP_USAGE_PAGE:
                continue
            result.append(info)

        # On G102/G203 Lightsync the working HID++ collection is usage 0x0002.
        # Some other models expose it as usage 0x0001, so open() probes both.
        result.sort(
            key=lambda item: (
                item.get("usage") != 0x0002,
                item.get("interface_number", 0),
            )
        )
        return result

    @property
    def connected(self) -> bool:
        return self._dev is not None

    def open(self, path=None) -> None:
        """Open the HID++ control interface. Raises HidppError if unavailable."""
        self.close()
        candidates = self.enumerate()
        if not candidates:
            raise HidppError(
                "Мышь Logitech G102/G203 Lightsync не найдена. "
                "Проверьте USB-подключение и закройте Logitech G HUB."
            )

        if path is not None:
            candidates = [item for item in candidates if item.get("path") == path]
            if not candidates:
                raise HidppError("Указанный HID-интерфейс не найден")

        errors: List[str] = []
        for chosen in candidates:
            dev = hid.device()
            try:
                dev.open_path(chosen["path"])
                dev.set_nonblocking(1)
            except Exception as exc:
                errors.append(f"usage 0x{chosen.get('usage', 0):04X}: {exc}")
                try:
                    dev.close()
                except Exception:
                    pass
                continue

            self._dev = dev
            self.pid = chosen.get("product_id")
            self.product = chosen.get("product_string") or SUPPORTED_PIDS.get(
                self.pid, ""
            )
            self.path = chosen.get("path")
            self._feature_cache.clear()

            # Probe: only the real HID++ collection answers this request.
            try:
                response = self._request(
                    FEATURE_IRoot,
                    0x00,
                    bytes(((FEATURE_DPI >> 8), FEATURE_DPI & 0xFF, 0x00, 0x00)),
                    timeout=0.4,
                    attempts=1,
                )
                if response and response[0]:
                    return
                errors.append(f"usage 0x{chosen.get('usage', 0):04X}: нет ответа")
            except HidppError as exc:
                errors.append(f"usage 0x{chosen.get('usage', 0):04X}: {exc}")

            self._dev = None
            try:
                dev.close()
            except Exception:
                pass

        raise HidppError(
            "Не удалось установить HID++ связь. Закройте Logitech G HUB и "
            "переподключите мышь. " + (" | ".join(errors) if errors else "")
        )

    def close(self) -> None:
        with self._lock:
            if self._dev is not None:
                try:
                    self._dev.close()
                except Exception:
                    pass
            self._dev = None
            self._feature_cache.clear()

    # ----------------------------------------------------------------- protocol
    def _drain(self) -> None:
        """Discard stale input reports (best effort)."""
        if self._dev is None:
            return
        for _ in range(8):
            try:
                data = self._dev.read(20, 1)
            except OSError:
                break
            if not data:
                break

    def _request(
        self,
        feature_index: int,
        function: int,
        params: bytes = b"",
        timeout: float = 1.0,
        attempts: int = 2,
    ) -> bytes:
        """Send one HID++ 2.0 request and return its parameter bytes."""
        if self._dev is None:
            raise HidppError("Устройство не подключено")

        payload = bytearray(20)
        payload[0] = REPORT_ID
        payload[1] = DEVICE_INDEX
        payload[2] = feature_index
        payload[3] = ((function & 0x0F) << 4) | SOFTWARE_ID
        body = params[:16]
        payload[4 : 4 + len(body)] = body

        with self._lock:
            for _ in range(attempts):
                self._drain()
                try:
                    written = self._dev.write(bytes(payload))
                except Exception as exc:
                    raise HidppError(f"Ошибка отправки HID++: {exc}") from exc
                if written is not None and written < 0:
                    raise HidppError(
                        "Windows отклонил HID++ запрос (write = -1). "
                        "Закройте Logitech G HUB и переподключите мышь."
                    )

                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    remaining = max(1, int((deadline - time.monotonic()) * 1000) + 1)
                    try:
                        resp = self._dev.read(20, min(50, remaining))
                    except OSError:
                        resp = []
                    if not resp:
                        time.sleep(0.005)
                        continue
                    if len(resp) < 7 or resp[0] != REPORT_ID:
                        continue
                    if resp[2] == 0xFF:  # HID++ error report
                        code = resp[5] if len(resp) > 5 else 0
                        raise HidppError(
                            f"HID++ error 0x{code:02X} "
                            f"(feature 0x{feature_index:02X}, fn {function})"
                        )
                    if resp[2] != feature_index:
                        continue
                    if ((resp[3] >> 4) & 0x0F) != function:
                        continue
                    return bytes(resp[4:])

            raise HidppError(
                f"Устройство не ответило (feature 0x{feature_index:02X}, fn {function})"
            )

    def _find_feature(self, feature_id: int) -> int:
        """Return the runtime feature index, or 0 if the device lacks it."""
        if feature_id in self._feature_cache:
            return self._feature_cache[feature_id]
        response = self._request(
            FEATURE_IRoot,
            0x00,
            bytes(((feature_id >> 8) & 0xFF, feature_id & 0xFF, 0x00, 0x00)),
        )
        index = response[0] if response else 0
        self._feature_cache[feature_id] = index
        return index

    def get_feature_index(self, feature_id: int) -> int:
        index = self._find_feature(feature_id)
        if not index:
            raise HidppError(f"Устройство не поддерживает feature 0x{feature_id:04X}")
        return index

    def _require(self, feature_id: int, name: str) -> int:
        index = self._find_feature(feature_id)
        if not index:
            raise HidppError(f"{name} (0x{feature_id:04X}) не поддерживается устройством")
        return index

    # -------------------------------------------------------------- onboard mode
    def get_onboard_mode(self) -> int:
        """Return the onboard-profile mode (0x01 = enabled, 0x02 = host/disabled)."""
        index = self._find_feature(FEATURE_ONBOARD_PROFILES)
        if not index:
            return 0
        response = self._request(index, 0x02, b"\x00")
        return response[0] if response else 0

    def ensure_host_mode(self) -> bool:
        """
        Switch the mouse to host/software mode.

        While an onboard profile is enabled, feature 0x8060 rejects
        setReportRate with HID++ error 0x02 (InvalidArgument), because the
        report rate is owned by the profile stored in the mouse.
        """
        index = self._find_feature(FEATURE_ONBOARD_PROFILES)
        if not index:
            return False
        try:
            if self._request(index, 0x02, b"\x00")[0] != 0x02:
                self._request(index, 0x01, b"\x02")
            return True
        except HidppError:
            return False

    # --------------------------------------------------------------------- DPI
    def get_dpi_info(self) -> DpiInfo:
        feature = self._require(FEATURE_DPI, "AdjustableDpi")
        sensor_count = self._request(feature, 0x00, b"\x00")[0] or 1

        raw = self._request(feature, 0x01, b"\x00")
        entries: List[int] = []
        # Response: sensor index echo + up to six big-endian 16-bit entries.
        for offset in range(1, 14, 2):
            if offset + 1 >= len(raw):
                break
            value = _be16(raw, offset)
            if value == 0:
                break
            entries.append(value)

        # Some firmware omits the echo byte; retry from offset 0.
        if not entries:
            for offset in range(0, 14, 2):
                value = _be16(raw, offset)
                if value == 0:
                    break
                entries.append(value)

        if len(entries) >= 3 and (entries[1] & 0xE000) == 0xE000:
            minimum = entries[0]
            step = entries[1] - 0xE000
            maximum = entries[2]
            levels = list(range(minimum, maximum + 1, step)) if step else [minimum, maximum]
        elif entries:
            levels = sorted({value for value in entries if value < 0xE000})
            minimum, maximum = levels[0], levels[-1]
            step = levels[1] - levels[0] if len(levels) > 1 else 50
        else:
            minimum, maximum, step, levels = 50, 8000, 50, []

        current_raw = self._request(feature, 0x02, b"\x00")
        current = _be16(current_raw, 1) if len(current_raw) >= 3 else 0
        default = _be16(current_raw, 3) if len(current_raw) >= 5 else 0

        return DpiInfo(
            sensor_count=sensor_count,
            minimum=minimum,
            maximum=maximum,
            step=step or 50,
            current=current,
            default=default,
            levels=levels,
        )

    def get_dpi(self) -> int:
        feature = self._require(FEATURE_DPI, "AdjustableDpi")
        raw = self._request(feature, 0x02, b"\x00")
        return _be16(raw, 1) if len(raw) >= 3 else 0

    def set_dpi(self, dpi: int, sensor: int = 0) -> int:
        feature = self._require(FEATURE_DPI, "AdjustableDpi")
        self.ensure_host_mode()
        dpi = max(1, min(0xDFFF, int(dpi)))
        self._request(
            feature,
            0x03,
            bytes((sensor, (dpi >> 8) & 0xFF, dpi & 0xFF, 0x00)),
        )
        return dpi

    # ------------------------------------------------------------ polling rate
    def get_supported_polling_rates(self) -> List[int]:
        feature = self._require(FEATURE_REPORT_RATE, "AdjustableReportRate")
        mask = self._request(feature, 0x00, b"\x00")[0]
        rates = [hz for bit, hz in enumerate((125, 250, 500, 1000)) if mask & (1 << bit)]
        return rates or [125, 250, 500, 1000]

    def get_polling_rate(self) -> int:
        feature = self._require(FEATURE_REPORT_RATE, "AdjustableReportRate")
        ms = self._request(feature, 0x01, b"\x00")[0]
        if ms <= 1:
            return 1000
        if ms <= 2:
            return 500
        if ms <= 4:
            return 250
        return 125

    def set_polling_rate(self, hz: int) -> int:
        feature = self._require(FEATURE_REPORT_RATE, "AdjustableReportRate")
        hz = int(hz)
        if hz not in POLLING_MS:
            raise HidppError(f"Неподдерживаемая частота опроса: {hz} Hz")
        self.ensure_host_mode()
        self._request(feature, 0x02, bytes((POLLING_MS[hz], 0x00, 0x00, 0x00)))
        return hz

    # ---------------------------------------------------------------- lighting
    def get_lighting_info(self) -> LightingInfo:
        rgb_index = self._find_feature(FEATURE_RGB_EFFECTS)
        if rgb_index:
            info = self._request(rgb_index, 0x00, bytes((0xFF, 0xFF, 0x00)))
            cluster_count = info[2] if len(info) > 2 else 1
            effects: Dict[int, int] = {}

            for cluster in range(max(1, min(cluster_count, 4))):
                cluster_info = self._request(
                    rgb_index, 0x00, bytes((cluster, 0xFF, 0x00))
                )
                effect_count = cluster_info[4] if len(cluster_info) > 4 else 0
                for effect_index in range(effect_count):
                    effect = self._request(
                        rgb_index, 0x00, bytes((cluster, effect_index, 0x00))
                    )
                    if len(effect) >= 4:
                        effect_id = _be16(effect, 2)
                        effects.setdefault(effect_id, effect_index)
            return LightingInfo(
                FEATURE_RGB_EFFECTS, rgb_index, cluster_count, effects
            )

        legacy_index = self._find_feature(FEATURE_COLOR_LED_EFFECTS)
        if legacy_index:
            return LightingInfo(FEATURE_COLOR_LED_EFFECTS, legacy_index, 1, {})

        raise HidppError("Подсветка Lightsync (0x8071/0x8070) не поддерживается")

    @staticmethod
    def _period_from_speed(speed: int) -> int:
        """Map UI speed 1..100 to an effect period in ms (1000..8000)."""
        speed = max(1, min(100, int(speed)))
        return int(8000 - (speed - 1) * 7000 / 99)

    def set_lighting(
        self,
        mode: str,
        rgb: Tuple[int, int, int],
        brightness: int = 100,
        speed: int = 60,
    ) -> None:
        """
        mode: "static" | "breathing" | "cycle" | "wave"
        rgb:  (r, g, b), each 0..255
        """
        if mode not in EFFECT_IDS:
            raise HidppError(f"Неизвестный режим подсветки: {mode}")

        self.ensure_host_mode()
        info = self.get_lighting_info()
        brightness = max(1, min(100, int(brightness)))
        red, green, blue = (max(0, min(255, int(c))) for c in rgb)
        params = bytearray(10)
        period = self._period_from_speed(speed)

        if mode == "static":
            # Brightness has no dedicated field for the static effect:
            # scale the colour instead.
            params[0] = red * brightness // 100
            params[1] = green * brightness // 100
            params[2] = blue * brightness // 100
            params[3] = 0x00  # ramp
        elif mode == "breathing":
            params[0], params[1], params[2] = red, green, blue
            params[3] = (period >> 8) & 0xFF
            params[4] = period & 0xFF
            params[5] = 0x00  # form
            params[6] = brightness
        elif mode == "cycle":
            params[5] = (period >> 8) & 0xFF
            params[6] = period & 0xFF
            params[7] = brightness
        elif mode == "wave":
            params[6] = (period >> 8) & 0xFF
            params[7] = period & 0xFF
            params[8] = 0x01  # direction

        if info.feature_id == FEATURE_RGB_EFFECTS:
            # Put the LED controller under software control first; otherwise
            # the onboard profile may immediately overwrite our effect.
            self._request(info.feature_index, 0x05, RGB_SW_CONTROL_PRELUDE)

            effect_index = info.effects.get(EFFECT_IDS[mode])
            if effect_index is None:
                effect_index = DEFAULT_EFFECT_INDEX[mode]

            # 0x8071 fn 1: [cluster, cluster_effect_index, 10 param bytes,
            #               persistence]  (persistence 0x01 = volatile)
            request = bytes((0x00, effect_index)) + bytes(params) + b"\x01"
            self._request(info.feature_index, 0x01, request)
            return

        # 0x8070 fallback: fn 3 (set effect), [zone, effect_id, 10 params].
        request = bytes((0x00, EFFECT_IDS[mode])) + bytes(params)
        self._request(info.feature_index, 0x03, request)


# --------------------------------------------------------------------- CLI test
def _main() -> None:
    """Diagnostic entry point: python hid_backend.py"""
    mouse = G102Mouse()
    found = G102Mouse.enumerate()
    if not found:
        print("Устройство не найдено.")
        return

    for item in found:
        print(
            f"PID=0x{item.get('product_id', 0):04X} "
            f"iface={item.get('interface_number')} "
            f"usage_page=0x{item.get('usage_page', 0):04X} "
            f"usage=0x{item.get('usage', 0):04X} "
            f"{item.get('product_string', '')}"
        )

    mouse.open()
    try:
        dpi = mouse.get_dpi_info()
        print(
            f"\nDPI: current={dpi.current} default={dpi.default} "
            f"range={dpi.minimum}-{dpi.maximum} step={dpi.step}"
        )
        print("Polling:", mouse.get_polling_rate(), "Hz")
        try:
            light = mouse.get_lighting_info()
            print(
                f"Lighting: feature=0x{light.feature_id:04X} "
                f"clusters={light.cluster_count} effects={light.effects}"
            )
        except HidppError as exc:
            print("Lighting:", exc)
    finally:
        mouse.close()


if __name__ == "__main__":
    _main()
