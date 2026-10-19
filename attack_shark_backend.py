"""
HID backend for the Attack Shark X11 gaming mouse.

Unlike the Logitech devices, the X11 does not speak HID++. It exposes a
vendor configuration interface (USB interface 2) that accepts *feature
reports* with a fixed layout and a simple checksum. Settings are stored in
the mouse itself, so every write is persisted by the firmware.

Report layout (see docs in https://github.com/HarukaYamamoto0/attack-shark-x11-driver):

    report 0x04  DPI                (read 56 bytes; short write in wired mode)
    report 0x05  lighting/user prefs(read 15 bytes; short write in wired mode)
    report 0x06  polling rate       (9 bytes)
    report 0xA0  read permission    (send 8 bytes, then read 8 bytes)

Reading any report requires a permission request first; permission is
granted for a single read. The mouse acknowledges feature reports through
the interrupt endpoint with a 5-byte event:

    byte 0  0x03 (event opcode)
    byte 1  device id (0x55 for X11)
    byte 2  0x50 (feature report status)
    byte 3  status: 0x00 success, 0x01 failure
    byte 4  report id
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import hid
except ImportError as exc:  # pragma: no cover - only hit before pip install
    raise ImportError(
        "Не найден модуль hid. Установите зависимости: pip install -r requirements.txt"
    ) from exc

from hid_backend import DpiInfo, HidppError, LightingInfo

VENDOR_ID = 0x1D57
WIRED_PID = 0xFA55
WIRELESS_PID = 0xFA60

SUPPORTED_PIDS = {
    WIRED_PID: "Attack Shark X11 (USB)",
    WIRELESS_PID: "Attack Shark X11 (2.4 GHz)",
}

REPORT_DPI = 0x04
REPORT_LIGHTING = 0x05
REPORT_POLLING = 0x06
REPORT_PERMISSION = 0xA0

LEN_DPI = 0x38
LEN_LIGHTING = 0x0F
LEN_POLLING = 0x09
LEN_PERMISSION = 0x08

EVENT_OPCODE = 0x03
EVENT_FEATURE_STATUS = 0x50

DPI_MIN = 50
DPI_MAX = 26000
DPI_STEP = 50

POLLING_TO_BYTE = {125: 0x08, 250: 0x04, 500: 0x02, 1000: 0x01}
BYTE_TO_POLLING = {value: key for key, value in POLLING_TO_BYTE.items()}

# Light modes are stored in the high nibble of byte 3 (see report 0x05).
LIGHT_MODE = {
    "off": 0x0,
    "static": 0x1,
    "breathing": 0x2,
    "cycle": 0x3,        # "Neon" in the official software
    "color_breathing": 0x4,
}
MODE_NAMES = {value: key for key, value in LIGHT_MODE.items()}

# PAW3311 DPI table: maps a 50-DPI step (0 = 50 DPI) to the byte stored in
# the profile. The second half is used for 100-DPI steps above 5000.
DPI_3311 = [
    0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0E, 0x0F, 0x10, 0x11, 0x12, 0x13, 0x15, 0x16,
    0x17, 0x18, 0x19, 0x1B, 0x1C, 0x1D, 0x1E, 0x1F, 0x20, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x29, 0x2A, 0x2B, 0x2C,
    0x2D, 0x2F, 0x30, 0x31, 0x32, 0x33, 0x34, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x3B, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x43,
    0x44, 0x45, 0x46, 0x47, 0x48, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x51, 0x52, 0x53, 0x54, 0x55, 0x57, 0x58, 0x59,
    0x5A, 0x5B, 0x5C, 0x5E, 0x5F, 0x60, 0x61, 0x62, 0x63, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F,
    0x70, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7F, 0x80, 0x81, 0x82, 0x83, 0x84, 0x86,
    0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8D, 0x8E, 0x8F, 0x90, 0x91, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x9A, 0x9B, 0x9C,
    0x9D, 0x9E, 0x9F, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2,
    0xB3, 0xB5, 0xB6, 0xB7, 0xB8, 0xB9, 0xBB, 0xBC, 0xBD, 0xBE, 0xBF, 0xC0, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC9,
    0xCA, 0xCB, 0xCC, 0xCD, 0xCF, 0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xDB, 0xDD, 0xDE, 0xDF,
    0xE0, 0xE1, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xEA, 0xEB, 0x76, 0x77, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7F, 0x80,
    0x81, 0x82, 0x83, 0x84, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8D,
]

DEFAULT_DPI_VALUES = (800, 1600, 2400, 3200, 5000, 22000, 0, 0)
DEFAULT_DPI_COLORS = (
    (0xFF, 0x00, 0x00), (0x00, 0xFF, 0x00), (0x00, 0x00, 0xFF), (0xFF, 0xFF, 0x00),
    (0x00, 0xFF, 0xFF), (0xFF, 0x00, 0xFF), (0xFF, 0x40, 0x00), (0xFF, 0xFF, 0xFF),
)

# Sensor tuning bytes mirrored from the official software's defaults.
DPI_LIFT_OFF_ANGLE_SNAP = 0x00
DPI_MOTION_SYNC_RIPPLE = 0x01
DPI_ACTIVE_MASK = 0x3F
DPI_STAGE_FLAGS = 0x20
DPI_ACTIVE_INDICATOR = 0x02

LIGHTING_DEEP_SLEEP = 10         # minutes
LIGHTING_SLEEP_TIME = 0.5        # minutes
LIGHTING_KEY_RESPONSE = 8        # ms
LIGHTING_BRIGHTNESS = 8          # 1..8
LIGHTING_LED_SPEED = 3           # 1..5


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def dpi_to_bytes(dpi: int) -> Tuple[int, int, bool]:
    """Encode a DPI value for the PAW3311 profile (x byte, y byte, double flag)."""
    clamped = _clamp(dpi, DPI_MIN, DPI_MAX)

    if clamped == 20100:
        return 0xEB, 1, True

    is_double = False
    target = clamped
    if clamped > 10000:
        target = int(clamped / 2 + 0.5)
        is_double = True

    if target > 10000:
        extra_index = (target - 10100) // 100
        combined = 199 + extra_index
        return combined & 0xFF, (combined >> 8) & 0xFF, is_double
    if target > 5000 and target % 100 == 0:
        index = target // 100 - 1
        return DPI_3311[index] if 0 <= index < len(DPI_3311) else 0, 1, is_double

    index = (target - DPI_MIN) // DPI_STEP
    x_byte = DPI_3311[index] if 0 <= index < len(DPI_3311) else 0
    return x_byte, 0, is_double


def bytes_to_dpi(x_byte: int, y_byte: int, is_double: bool) -> int:
    """Decode a PAW3311 profile entry (same rules as the reference driver).

    Values above 20,000 share their bytes with ordinary values, so the
    reference format cannot represent them unambiguously; decoding follows
    the driver's table lookup, which keeps the error small except for the
    combined-index range.
    """
    if x_byte == 0 and y_byte == 0:
        return 0
    if y_byte == 0:
        try:
            index = DPI_3311.index(x_byte)
        except ValueError:
            index = -1
        if index >= 0:
            value = index * DPI_STEP + DPI_STEP
        elif is_double:
            # Bytes outside the table can only come from the combined-index
            # encoding used above 20,000 DPI.
            value = 10100 + (x_byte - 199) * 100
        else:
            value = DPI_MIN
    elif y_byte == 1:
        try:
            index = DPI_3311.index(x_byte)
        except ValueError:
            index = -1
        value = index * 100 + 100 if index >= 0 else 100
    else:
        combined = (y_byte << 8) | x_byte
        value = 10100 + (combined - 199) * 100

    if is_double:
        if x_byte == 0xEB:
            return 20100
        value *= 2
    return min(value, DPI_MAX)


def _checksum16(buffer: bytearray, start: int, end: int) -> int:
    return sum(buffer[start : end + 1]) & 0xFFFF


class AttackSharkX11:
    """Small, thread-safe feature-report client for the Attack Shark X11."""

    backend_key = "attack_shark"
    backend_name = "Attack Shark HID"
    vendor_id = VENDOR_ID
    max_levels = 8

    def __init__(self) -> None:
        self._dev = None
        self._events = None
        self._owns_events = False
        self._lock = threading.RLock()
        self.pid: Optional[int] = None
        self.product = ""
        self.path = None

    # ------------------------------------------------------------------ device
    @staticmethod
    def _candidates() -> List[dict]:
        try:
            devices = hid.enumerate()
        except Exception:
            return []
        matching = [
            item
            for item in devices
            if item.get("vendor_id") == VENDOR_ID
            and item.get("product_id") in SUPPORTED_PIDS
        ]
        preferred = [
            item
            for item in matching
            if item.get("interface_number") == 2 and item.get("usage_page") == 0x0B
        ]
        if not preferred:
            preferred = [
                item for item in matching if item.get("interface_number") == 2
            ]
        if not preferred:
            preferred = matching

        seen = set()
        unique: List[dict] = []
        for item in preferred:
            key = (item.get("path"), item.get("usage_page"), item.get("usage"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    @classmethod
    def enumerate(cls) -> List[dict]:
        """Return the vendor configuration collections of connected X11 mice."""
        return cls._candidates()

    @property
    def connected(self) -> bool:
        return self._dev is not None

    @property
    def connection_name(self) -> str:
        return "2.4 GHz" if self.pid == WIRELESS_PID else "USB"

    @property
    def wired(self) -> bool:
        return self.pid != WIRELESS_PID

    def _event_path(self) -> Optional[bytes]:
        """Find the interrupt-IN collection that carries command confirmations."""
        try:
            devices = hid.enumerate()
        except Exception:
            return None
        for item in devices:
            if (
                item.get("vendor_id") == VENDOR_ID
                and item.get("product_id") == self.pid
                and item.get("interface_number") == 2
                and item.get("usage_page") == 0x0A
                and item.get("path") != self.path
            ):
                return item.get("path")
        return None

    def open(self, path=None) -> None:
        """Open the configuration interface. Raises HidppError if unavailable."""
        self.close()
        candidates = self.enumerate()
        if not candidates:
            raise HidppError(
                "Мышь Attack Shark X11 не найдена. Подключите её по USB "
                "или через 2.4 ГГц приёмник."
            )
        if path is not None:
            candidates = [item for item in candidates if item.get("path") == path]
            if not candidates:
                raise HidppError("Указанный HID-интерфейс Attack Shark не найден")

        errors: List[str] = []
        for chosen in candidates:
            dev = hid.device()
            try:
                dev.open_path(chosen["path"])
            except Exception as exc:  # noqa: BLE001 - reported below
                errors.append(f"{chosen.get('path')}: {exc}")
                try:
                    dev.close()
                except Exception:
                    pass
                continue

            self._dev = dev
            self._events = None
            self._owns_events = False
            self.pid = chosen.get("product_id")
            self.product = chosen.get("product_string") or SUPPORTED_PIDS.get(
                self.pid, "Attack Shark X11"
            )
            self.path = chosen.get("path")

            try:
                self._read_report(REPORT_POLLING, LEN_POLLING, attempts=1)
            except HidppError as exc:
                errors.append(f"{self.product or 'X11'}: {exc}")
                self._close_devices()
                continue

            event_path = self._event_path()
            if event_path is not None:
                try:
                    events = hid.device()
                    events.open_path(event_path)
                    events.set_nonblocking(1)
                    self._events = events
                    self._owns_events = True
                except Exception:
                    self._events = None
                    self._owns_events = False
            return

        self._close_devices()
        raise HidppError(
            "Не удалось связаться с Attack Shark X11. Переподключите мышь "
            "или переключите её в режим USB. " + (" | ".join(errors) if errors else "")
        )

    def _close_devices(self) -> None:
        if self._events is not None and self._owns_events:
            try:
                self._events.close()
            except Exception:
                pass
        self._events = None
        self._owns_events = False
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None

    def close(self) -> None:
        with self._lock:
            self._close_devices()

    # ----------------------------------------------------------------- protocol
    def _require_device(self) -> None:
        if self._dev is None:
            raise HidppError("Устройство не подключено")

    def _get_feature(self, report_id: int, length: int) -> bytes:
        self._require_device()
        try:
            data = self._dev.get_feature_report(report_id, length)
        except Exception as exc:  # noqa: BLE001 - normalised below
            raise HidppError(f"Ошибка чтения отчёта 0x{report_id:02X}: {exc}") from exc
        return bytes(data or b"")

    def _send_feature(self, payload: Iterable[int]) -> None:
        self._require_device()
        data = bytes(payload)
        try:
            written = self._dev.send_feature_report(data)
        except Exception as exc:  # noqa: BLE001 - normalised below
            raise HidppError(f"Ошибка отправки отчёта 0x{data[0]:02X}: {exc}") from exc
        if written is not None and written < 0:
            raise HidppError(
                "Windows отклонил запрос к Attack Shark X11. "
                "Переподключите мышь или закройте официальное ПО."
            )

    def _drain_events(self) -> None:
        if self._events is None:
            return
        for _ in range(16):
            try:
                data = self._events.read(5, 0)
            except Exception:
                return
            if not data:
                return

    def _wait_ack(self, report_id: int, timeout: float = 0.6) -> None:
        if self._events is None:
            time.sleep(0.03)
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data = self._events.read(5, 12)
            except Exception:
                return
            if not data:
                time.sleep(0.01)
                continue
            data = bytes(data)
            if (
                len(data) >= 5
                and data[2] == EVENT_FEATURE_STATUS
                and data[4] == report_id
            ):
                if data[3] != 0x00:
                    raise HidppError(
                        f"Attack Shark X11 отклонил команду 0x{report_id:02X}"
                    )
                return
        # Missing confirmations happen occasionally; the write itself succeeded.
        time.sleep(0.03)

    def _send_command(self, payload: Iterable[int], report_id: int) -> None:
        with self._lock:
            self._drain_events()
            self._send_feature(payload)
            self._wait_ack(report_id)

    def _read_report(
        self, report_id: int, length: int, parameter: int = 0x01, attempts: int = 2
    ) -> bytes:
        """Request one-shot read permission, then fetch the report."""
        last_error: Optional[Exception] = None
        for _ in range(max(1, attempts)):
            try:
                permission = bytes(
                    (
                        REPORT_PERMISSION,
                        report_id & 0xFF,
                        length & 0xFF,
                        0x00,
                        parameter & 0xFF,
                        0x00,
                        0x00,
                        0x00,
                    )
                )
                with self._lock:
                    self._drain_events()
                    self._send_feature(permission)
                time.sleep(0.25)

                status = self._get_feature(REPORT_PERMISSION, LEN_PERMISSION)
                if len(status) < 2 or status[1] != 0x01:
                    raise HidppError(
                        f"Устройство не разрешило чтение отчёта 0x{report_id:02X}"
                    )
                data = self._get_feature(report_id, length)
                if len(data) < length:
                    raise HidppError(
                        f"Короткий ответ 0x{report_id:02X}: {len(data)} из {length} байт"
                    )
                return data[:length]
            except HidppError as exc:
                last_error = exc
                time.sleep(0.08)
        raise last_error or HidppError("Не удалось прочитать настройки устройства")

    # --------------------------------------------------------------------- DPI
    @staticmethod
    def _decode_stage(buffer: bytes, index: int) -> int:
        x_byte = buffer[8 + index]
        y_byte = buffer[16 + index]
        is_double = bool(buffer[6] & (1 << index))
        return bytes_to_dpi(x_byte, y_byte, is_double)

    def _default_dpi_buffer(self) -> bytearray:
        buffer = bytearray(LEN_DPI)
        buffer[0] = REPORT_DPI
        buffer[1] = LEN_DPI
        buffer[2] = 0x01
        buffer[3] = DPI_LIFT_OFF_ANGLE_SNAP
        buffer[4] = DPI_MOTION_SYNC_RIPPLE
        buffer[5] = DPI_ACTIVE_MASK
        buffer[6] = DPI_STAGE_FLAGS
        buffer[7] = DPI_STAGE_FLAGS
        buffer[24] = 0x02
        for index, dpi in enumerate(DEFAULT_DPI_VALUES):
            self._encode_stage(buffer, index, dpi)
        for index, (red, green, blue) in enumerate(DEFAULT_DPI_COLORS):
            buffer[25 + index * 3 : 28 + index * 3] = bytes((red, green, blue))
        buffer[49] = DPI_ACTIVE_INDICATOR
        return buffer

    @staticmethod
    def _encode_stage(buffer: bytearray, index: int, dpi: int) -> None:
        if dpi <= 0:
            buffer[8 + index] = 0x00
            buffer[16 + index] = 0x00
            buffer[6] &= ~(1 << index) & 0xFF
            buffer[7] &= ~(1 << index) & 0xFF
            return
        x_byte, y_byte, is_double = dpi_to_bytes(dpi)
        buffer[8 + index] = x_byte
        buffer[16 + index] = y_byte
        if is_double:
            buffer[6] |= 1 << index
        else:
            buffer[6] &= ~(1 << index) & 0xFF
        # The Y-triple flag is unused by the X11 firmware.
        buffer[7] &= ~(1 << index) & 0xFF

    def _dpi_packet(self, levels: List[int], active_index: int, base=None) -> bytearray:
        buffer = bytearray(base) if base is not None else self._default_dpi_buffer()
        count = min(len(levels), 8)
        for index in range(8):
            self._encode_stage(buffer, index, levels[index] if index < count else 0)

        active_index = _clamp(active_index, 0, max(0, count - 1))
        buffer[5] = (1 << count) - 1 if count else 0
        buffer[24] = active_index + 1

        checksum = _checksum16(buffer, 3, 49)
        buffer[50] = (checksum >> 8) & 0xFF
        buffer[51] = checksum & 0xFF
        return buffer

    def _read_dpi_buffer(self) -> bytearray:
        data = self._read_report(REPORT_DPI, LEN_DPI)
        expected = (data[50] << 8) | data[51]
        if _checksum16(bytearray(data), 3, 49) != expected:
            raise HidppError("Повреждён ответ DPI Attack Shark (чек-сумма)")
        return bytearray(data)

    def get_dpi_info(self) -> DpiInfo:
        levels: List[int] = []
        current = 0
        try:
            buffer = self._read_dpi_buffer()
            levels = [self._decode_stage(buffer, index) for index in range(8)]
            stage = _clamp(buffer[24], 1, 8) - 1
            current = levels[stage]
            if current == 0:
                current = next((value for value in levels if value), 0)
        except HidppError:
            pass
        if current == 0:
            current = DEFAULT_DPI_VALUES[0]
        return DpiInfo(
            sensor_count=1,
            minimum=DPI_MIN,
            maximum=DPI_MAX,
            step=DPI_STEP,
            current=current,
            default=current,
            levels=[value for value in levels if value],
        )

    def get_dpi(self) -> int:
        return self.get_dpi_info().current

    def set_dpi(self, dpi: int) -> int:
        dpi = _clamp(dpi, DPI_MIN, DPI_MAX)
        try:
            buffer = self._read_dpi_buffer()
        except HidppError:
            buffer = self._default_dpi_buffer()
        stage = _clamp(buffer[24], 1, 8) - 1
        levels = [self._decode_stage(buffer, index) for index in range(8)]
        levels[stage] = dpi
        self.apply_dpi(levels, stage)
        return dpi

    def apply_dpi(self, levels: List[int], active_index: int) -> None:
        values = [int(value) for value in levels if int(value) > 0]
        if not values:
            return
        try:
            base = self._read_dpi_buffer()
        except HidppError:
            base = None
        packet = self._dpi_packet(values, active_index, base=base)
        length = 51 if self.wired else LEN_DPI
        self._send_command(packet[:length], REPORT_DPI)

    # ------------------------------------------------------------ polling rate
    def get_supported_polling_rates(self) -> List[int]:
        return [125, 250, 500, 1000]

    def get_polling_rate(self) -> int:
        data = self._read_report(REPORT_POLLING, LEN_POLLING)
        return BYTE_TO_POLLING.get(data[3], 0)

    def set_polling_rate(self, hz: int) -> int:
        hz = int(hz)
        if hz not in POLLING_TO_BYTE:
            raise HidppError(f"Неподдерживаемая частота опроса: {hz} Hz")

        packet = bytearray(LEN_POLLING)
        packet[0] = REPORT_POLLING
        packet[1] = LEN_POLLING
        packet[2] = 0x01  # profile id
        packet[3] = POLLING_TO_BYTE[hz]
        packet[4] = (~packet[3]) & 0xFF
        self._send_command(packet, REPORT_POLLING)
        return hz

    # ---------------------------------------------------------------- lighting
    def _default_lighting_buffer(self) -> bytearray:
        buffer = bytearray(LEN_LIGHTING)
        buffer[0] = REPORT_LIGHTING
        buffer[1] = LEN_LIGHTING
        buffer[2] = 0x01
        buffer[3] = LIGHT_MODE["off"] << 4
        buffer[4] = ((LIGHTING_DEEP_SLEEP & 0xF0) | LIGHTING_LED_SPEED) & 0xFF
        buffer[5] = (((LIGHTING_DEEP_SLEEP & 0x0F) << 4) | LIGHTING_BRIGHTNESS) & 0xFF
        buffer[6] = 0x00
        buffer[7] = 0xFF
        buffer[8] = 0x00
        buffer[9] = int(round(LIGHTING_SLEEP_TIME * 2)) & 0xFF
        buffer[10] = (LIGHTING_KEY_RESPONSE // 2) & 0xFF
        return buffer

    @staticmethod
    def _lighting_checksum(buffer: bytearray) -> None:
        checksum = _checksum16(buffer, 3, 10)
        buffer[11] = (checksum >> 8) & 0xFF
        buffer[12] = checksum & 0xFF

    def _read_lighting_buffer(self) -> bytearray:
        data = self._read_report(REPORT_LIGHTING, LEN_LIGHTING)
        expected = (data[11] << 8) | data[12]
        if _checksum16(bytearray(data), 3, 10) != expected:
            raise HidppError("Повреждён ответ подсветки Attack Shark (чек-сумма)")
        return bytearray(data)

    def get_lighting_info(self) -> LightingInfo:
        effects: Dict[int, int] = {}
        try:
            buffer = self._read_lighting_buffer()
            mode = buffer[3] >> 4
            effects = {mode: mode}
        except HidppError:
            pass
        return LightingInfo(
            feature_id=0x0305,
            feature_index=0,
            cluster_count=1,
            effects=effects,
        )

    def set_lighting(
        self,
        mode: str,
        rgb: Tuple[int, int, int],
        brightness: int = 100,
        speed: int = 60,
    ) -> None:
        if mode not in LIGHT_MODE or mode in ("off", "color_breathing"):
            raise HidppError(f"Неизвестный режим подсветки: {mode}")
        try:
            buffer = self._read_lighting_buffer()
        except HidppError:
            buffer = self._default_lighting_buffer()

        brightness_level = _clamp(round(brightness / 100 * 8), 1, 8)
        led_speed = _clamp(round(speed / 100 * 5), 1, 5)
        red, green, blue = (_clamp(value, 0, 255) for value in rgb)

        buffer[3] = (LIGHT_MODE[mode] << 4) & 0xFF
        buffer[4] = (buffer[4] & 0xF0) | led_speed
        buffer[5] = (buffer[5] & 0xF0) | brightness_level
        buffer[6] = red
        buffer[7] = green
        buffer[8] = blue
        self._lighting_checksum(buffer)

        length = 13 if self.wired else LEN_LIGHTING
        self._send_command(buffer[:length], REPORT_LIGHTING)

    # -------------------------------------------------------------- onboarding
    def get_onboard_mode(self) -> int:
        """The X11 has no onboard-profile mode; report host mode."""
        return 0x02


# --------------------------------------------------------------------- CLI test
def _main() -> None:
    """Diagnostic entry point: python attack_shark_backend.py"""
    devices = AttackSharkX11.enumerate()
    if not devices:
        print("Attack Shark X11 не найден.")
        return

    for item in devices:
        print(
            f"VID=0x{item.get('vendor_id', 0):04X} "
            f"PID=0x{item.get('product_id', 0):04X} "
            f"iface={item.get('interface_number')} "
            f"usage_page=0x{item.get('usage_page', 0):04X} "
            f"usage=0x{item.get('usage', 0):04X} "
            f"{item.get('product_string', '')}"
        )

    mouse = AttackSharkX11()
    mouse.open()
    try:
        dpi = mouse.get_dpi_info()
        print(
            f"\nDPI: current={dpi.current} range={dpi.minimum}-{dpi.maximum} "
            f"step={dpi.step} levels={dpi.levels}"
        )
        print("Polling:", mouse.get_polling_rate(), "Hz")
        light = mouse.get_lighting_info()
        print(f"Lighting: report 0x{light.feature_id:04X} effects={light.effects}")
    finally:
        mouse.close()


if __name__ == "__main__":
    _main()
