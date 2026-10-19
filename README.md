# Lightsync Control — Logitech G102/G203 & Attack Shark X11

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![License](https://img.shields.io/badge/license-MIT-2EE6A6)
![Protocol](https://img.shields.io/badge/protocol-HID%2B%2B%202.0%20%C2%B7%20Vendor%20HID-8B5CF6)
![Devices](https://img.shields.io/badge/devices-G102%20%2F%20G203%20%2F%20X11-2EE6A6)

A lightweight, driver-free replacement for vendor software for the **Logitech G102 / G203 Lightsync** (and **G203 Prodigy**) and the **Attack Shark X11** gaming mice. It talks to the mouse directly over **HID++ 2.0** (Logitech) or the mouse's **vendor HID feature-report protocol** (Attack Shark) using hidapi — no kernel driver, no libusb, no replacement of the system HID driver.

The UI is built with **PySide6** (Qt 6), adapts its layout to the window width, and supports system, light and dark themes. The device layer uses `hidapi` (imported as `hid`) and auto-detects which supported mouse is connected.

> **Unofficial project.** Not affiliated with or endorsed by Logitech or Attack Shark. Use at your own risk.

---

## Features

- **Two device families in one app** — Logitech G102/G203 Lightsync and Attack Shark X11; the connected mouse is detected automatically and the last used backend is preferred on the next launch.
- **DPI** — app-side presets, pick the active one. The editor range and step follow the connected sensor (G102/G203 report up to 8000 DPI; X11 supports 50–26000, step 50, up to 8 presets).
- **Automatic apply** — every change is saved and sent to the mouse after a short pause; there is no Apply button.
- **Polling rate** — 125 / 250 / 500 / 1000 Hz.
- **Lighting** — Static, Breathing and Color Cycle; color via presets, HEX input or a color picker; brightness and speed control.
- **Light, dark and system themes** — switch from the **appearance menu** or the segmented control in the **Application** section; the choice is saved.
- **Adaptive layout** — the settings column and the device/log panel sit side by side on wide windows and stack vertically on narrow ones.
- **Autostart and tray** — optional launch at Windows login; closing the window keeps the app in the notification area instead of quitting.
- **Saved profile** — `config.json` is created automatically and re-applied when the mouse reconnects.
- **Built-in diagnostics** — device log in the UI and headless CLIs (`python device_backend.py`, `python hid_backend.py`, `python attack_shark_backend.py`).
- **No vendor software required** — G HUB and the Attack Shark utility are not needed.

> DPI presets are stored in the app and applied individually. On Logitech mice the app does **not** reprogram the levels the physical DPI button cycles through — those live in the onboard profile. On the X11 the presets are written into the device's DPI slots (up to 8).

---

## Requirements

- Windows 10/11 (tested) — the code itself is portable, but macOS/Linux are untested and may need hidapi permissions (udev rules).
- Python 3.10+ (tested on 3.10).
- Logitech G HUB **must be closed** (fully, including the tray icon) while using a Logitech mouse. G HUB owns the same HID++ interface and will fight over the device. Close the Attack Shark utility as well when using the X11.

## Installation

### Portable executable

Download **`G102LightsyncControl.exe`** from the [latest release](https://github.com/ste4ik/g102-lightsync-control/releases/latest) and run it — Python is not required. The profile is stored in `%APPDATA%\G102 Lightsync Control\config.json`.

### From source

```powershell
git clone https://github.com/ste4ik/g102-lightsync-control.git
cd g102-lightsync-control
python -m pip install -r requirements.txt
```

Or manually:

```powershell
python -m pip install hidapi PySide6-Essentials
```

The **`hidapi`** package (by trezor) is a Python binding for hidapi. Its Windows wheel bundles the native library and installs the importable module named `hid`.

> If the old **`hid`** package by apmorton is installed (a ctypes wrapper that needs a separate `hidapi.dll`), remove it — it shadows the working module:
>
> ```powershell
> python -m pip uninstall hid -y
> python -m pip install hidapi
> ```

## Usage

```powershell
python main.py
```

Optionally double-click `run.bat` (it changes to its own folder, runs the app and keeps the window open on error).

The app scans for a supported mouse on startup and, if one is found, connects and applies the saved profile automatically. Settings made in the UI are **applied automatically**: discrete changes after a short pause, sliders as soon as you release them. Every change is saved to `config.json` right away. If you ever need to force a sync, use **Устройство → Применить сейчас** (`Ctrl+Enter`).

Closing the window (`X`) hides the app to the notification area instead of quitting: click the tray icon to bring it back, and use **Выход** in its menu to quit. Tick **Запускать при входе в Windows** in the **Приложение** section to start the app at login.

### Supported devices

**Logitech (HID++ 2.0)**

| USB PID | Model |
|---|---|
| `0xC084` | G102 / G203 Prodigy |
| `0xC092` | G102 / G203 Lightsync |
| `0xC093` | G102 Lightsync variant |
| `0xC09D` | G102 Lightsync (newer revision) |

**Attack Shark X11 (vendor HID, VID `0x1D57`)**

| USB PID | Connection |
|---|---|
| `0xFA55` | Wired USB |
| `0xFA60` | 2.4 GHz receiver |

The mouse identifies itself by its USB product string, so the UI shows the name reported by the device. When several supported mice are connected, the app prefers the one used last; press **Подключить мышь** to re-scan.

## Configuration

`config.json` is created next to `main.py` when running from source. The portable build stores it in `%APPDATA%\G102 Lightsync Control\config.json`. Missing or invalid values fall back to safe defaults.

```json
{
  "dpi": {
    "levels": [800, 1600, 3200],
    "active_level": 0
  },
  "polling_rate": 1000,
  "lighting": {
    "mode": "static",
    "color": "#00E5A0",
    "brightness": 100,
    "speed": 60
  },
  "app": {
    "autostart": false,
    "theme": "system",
    "last_device": ""
  }
}
```

| Field | Meaning |
|---|---|
| `dpi.levels` | Preset list, each clamped to 50–26000 and rounded to a multiple of 50 (the editor narrows to the connected sensor's range) |
| `dpi.active_level` | Index of the preset that is applied |
| `polling_rate` | One of `125`, `250`, `500`, `1000` |
| `lighting.mode` | `static`, `breathing` or `cycle` |
| `lighting.color` | `#RRGGBB` |
| `lighting.brightness` | 1–100 |
| `lighting.speed` | 1–100 (breathing/cycle only; static ignores it) |
| `app.autostart` | Mirrors the `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` entry |
| `app.theme` | `system`, `light` or `dark` |
| `app.last_device` | Last successfully opened backend (`logitech` or `attack_shark`), used to pick the device when both are present |

## Troubleshooting

If the mouse is not detected or settings do not apply:

1. **Close vendor software completely** — G HUB (`lghub_agent`, `lghub_system_tray`) for Logitech, the Attack Shark utility for the X11.
2. Run the headless diagnostic:
   ```powershell
   python device_backend.py
   ```
   It lists every supported mouse that is currently connected. For deeper detail use `python hid_backend.py` (Logitech) or `python attack_shark_backend.py` (X11); they print matching HID collections with PID, interface and usage, then the DPI range, current polling rate and lighting state. They do not change any settings.
3. **"Access denied"** — close the vendor utility and/or run the terminal as Administrator.
4. Make sure the correct `hid` module is installed (see the `hidapi` note above).
5. On the X11, use the **USB cable or the 2.4 GHz receiver** — Bluetooth is not supported. Replug the mouse and press **Подключить мышь** in the app.

## How it works

All traffic is HID++ 2.0 **long reports**:

```
byte 0      0x11                     report ID (20-byte report)
byte 1      0xFF                     device index (wired mouse)
byte 2      feature index            resolved through IRoot (0x0000)
byte 3      (function << 4) | 0x0B   function + software ID
bytes 4–19  parameters
```

**Transport.** On the G102/G203 Lightsync, HID++ uses regular HID output/input reports: a request is a 20-byte `hidapi write()` with report ID `0x11`, and the reply is a `read()` with the same report ID. Feature reports (`send_feature_report`) do not work on this device. The backend walks the vendor collections (`usage_page 0xFF00`), probes each one with `IRoot → 0x2201`, and keeps the one that answers.

Feature index lookup: `IRoot = 0x0000`, function `0x00`, parameters `[id_hi, id_lo, 0, 0]`; the reply is `[feature_index, type, version]`.

| Feature | Purpose | Functions used |
|---|---|---|
| `0x2201` | Adjustable DPI | `0` sensor count, `1` DPI list, `2` get DPI, `3` set DPI |
| `0x8060` | Adjustable Report Rate | `0` list, `1` get (ms), `2` set (ms) |
| `0x8071` | RGB Effects (Lightsync) | `0` info, `1` set cluster effect, `5` software control |
| `0x8070` | Color LED Effects (legacy fallback) | `0` info, `1` zone info, `2` effect info, `3` set effect |
| `0x8100` | Onboard Profiles | `1` set mode, `2` get mode |

**Lighting.** Before setting an effect the app switches the LED controller to software control (`0x8071` fn `5`, params `01 03 05`). Effect packets are laid out as:

```
Static:     [cluster, effect_index, R, G, B, 0×7, persistence=1]
Breathing:  [cluster, effect_index, R, G, B, period_hi, period_lo, 0, brightness, 0×3, persistence=1]
Cycle:      [cluster, effect_index, 0×5, period_hi, period_lo, brightness, 0×2, persistence=1]
Wave:       [cluster, effect_index, 0×6, period_hi, period_lo, direction, 0, persistence=1]
```

`period` is big-endian milliseconds (1000–8000, mapped from the UI speed). Brightness is 1–100; for Static there is no brightness field, so the color is scaled instead. The protocol effect IDs returned by `getEffectInfo` are `0x01` static, `0x03` cycle, `0x04` wave, `0x0A` breathing; they are distinct from the per-cluster effect indexes (1–4 by default), which the app tries to discover at runtime and falls back to when discovery fails.

**Onboard profile.** While an onboard profile is enabled (`0x8100` mode `0x01`), the firmware rejects polling-rate changes (`0x8060` → `InvalidArgument`), because the rate belongs to the profile. The app therefore switches the mouse to host mode (`0x8100` fn `1`, parameter `0x02`) before applying settings — the same thing G HUB does. This is a device state change and it persists beyond the app.

### Attack Shark X11 protocol

The X11 uses vendor HID **feature reports** (not HID++). The app opens interface 2 (`usage_page 0x0B`) for commands and keeps the matching interrupt-IN collection (`usage_page 0x0A`) open to read acknowledgements. The wired and wireless variants take slightly different report lengths.

| Report | Purpose | Length (wireless / wired) |
|---|---|---|
| `0x04` | DPI slots, active slot, sensor flags | 56 / 51 |
| `0x05` | Lighting mode, color, brightness, speed | 15 / 13 |
| `0x06` | Polling rate | 9 / 9 |
| `0xA0` | Permission handshake before each write | 8 / 8 |

- **Checksums** — the DPI report ends with a 16-bit big-endian sum of bytes 3–49; the lighting report with a sum of bytes 3–10. The polling report uses a one-byte complement (`byte[4] = ~byte[3]`).
- **Permission** — before a write the app sends `0xA0` (8 bytes), waits 250 ms, reads it back and requires `byte[1] == 0x01`.
- **Acknowledgement** — a successful write is confirmed by a 5-byte event `[0x03, device_id, 0x50, status, report_id]` on the event interface. Writes are paced to avoid dropping packets.
- **DPI** — the PAW3311 sensor uses a 50-step lookup table; slots are read back, modified (only the presets and active slot are touched) and written, so unrelated settings such as lift-off, ripple control and debounce are preserved.
- **Lighting** — mode in the high nibble of byte 3 (`0x1` static, `0x2` breathing, `0x3` neon/cycle), brightness 1–8, LED speed 1–5, RGB in bytes 6–8. The buffer is read first and unrelated fields are kept.
- **Polling** — `125 → 0x08`, `250 → 0x04`, `500 → 0x02`, `1000 → 0x01`.

The protocol implementation is based on [HarukaYamamoto0/attack-shark-x11-driver](https://github.com/HarukaYamamoto0/attack-shark-x11-driver/).

References:

- HID++ 2.0 Adjustable DPI: <https://www.lekensteyn.nl/files/logitech/x2201_adjustabledpi.html>
- Protocol write-up: <https://github.com/kasik96/opengcontrol/blob/main/docs/PROTOCOL.md>
- Working Lightsync packet reference: <https://github.com/smasty/g203-led>
- libratbag (`0x8071` / `0x8060`): <https://github.com/libratbag/libratbag>

## Project structure

```
G102_Lightsync_Control/
├── device_backend.py       # unified detection/selection of supported mice
├── hid_backend.py          # Logitech HID++ 2.0: discovery, DPI, polling rate, RGB
├── attack_shark_backend.py # Attack Shark X11 vendor HID protocol
├── gui.py                  # PySide6 UI + themes + responsive layout + tray/autostart
├── main.py                 # entry point
├── requirements.txt
├── build_exe.ps1     # one-file Windows build (PyInstaller)
├── run.bat           # Windows launcher
├── assets/           # Lucide mouse SVG, check marks, generated app icon (PNG/ICO)
├── tools/            # make_icon.py, version_info.txt
├── LICENSE
└── README.md
```

`config.json`, `build/`, `dist/` and `__pycache__/` are generated locally and ignored by Git.

## Building an executable

```powershell
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

The result is `dist\G102LightsyncControl.exe` — a single windowed file with the icon, Qt runtime and `assets/` bundled. The frozen build keeps its profile in `%APPDATA%\G102 Lightsync Control\`.

## Limitations

- Settings are written as **volatile** — the app never writes to flash memory or edits onboard profiles. Reconnecting or rebooting requires re-applying the profile (which happens automatically on connect). On the X11 the DPI slots are part of the device profile, so the presets themselves are written there.
- The app does not watch for the mouse being unplugged; use **Переподключить** after replugging.
- Running alongside G HUB or the Attack Shark utility causes conflicts and flickering.
- The mouse may briefly stutter when the DPI or polling rate changes — this is normal.
- `0x8070` (legacy lighting) is implemented only as a basic fallback and is far less tested than `0x8071`.
- The X11 backend was written against the reference driver's protocol and has not been validated on every firmware revision. The X11 exposes only Static, Breathing and Neon (color cycle) through this app, and brightness/speed are quantized to the device's 1–8 / 1–5 steps.
- On the X11, DPI values above 20,000 share their encoded bytes with ordinary values in the reference format, so the value read back from the device after reconnecting may differ from the preset. Values up to 20,000 round-trip exactly (or within the 50 DPI step).
- No automated tests or CI yet.

## Contributing

Issues and pull requests are welcome. If you test the app on another G102/G203 revision or X11 firmware, Linux or macOS, please include the output of `python device_backend.py` and the matching backend diagnostic — it is the most useful troubleshooting information.

## License

[MIT](LICENSE) © G102 Lightsync Control authors

The UI runs on Qt via [PySide6](https://doc.qt.io/qtforpython-6/) (LGPLv3). The mouse icon is [Lucide “mouse”](https://lucide.dev/icons/mouse) (ISC); see [`assets/README.md`](assets/README.md) for attribution. The application icon is generated from that SVG by `tools/make_icon.py`. The Attack Shark X11 protocol implementation is based on [HarukaYamamoto0/attack-shark-x11-driver](https://github.com/HarukaYamamoto0/attack-shark-x11-driver/).

---

# Русский

Лёгкая замена фирменному ПО для мышей **G102 / G203 Lightsync** (и **G203 Prodigy**), а также **Attack Shark X11**. Работает напрямую по **HID++ 2.0** (Logitech) или по **вендорному HID-протоколу** мыши (Attack Shark) через hidapi — без драйверов, libusb и замены системного HID-драйвера.

Интерфейс построен на **PySide6** (Qt 6): раскладка подстраивается под ширину окна, доступны системная, светлая и тёмная темы. Поддерживаемое устройство определяется автоматически.

> **Неофициальный проект**, не связан с Logitech и Attack Shark. Используйте на свой риск.

## Возможности

- **Две линейки устройств в одном приложении** — Logitech G102/G203 Lightsync и Attack Shark X11; подключённая мышь определяется автоматически, а при следующем запуске предпочитается последняя использованная.
- **DPI** — уровни-пресеты в приложении и выбор активного. Диапазон и шаг подстраиваются под сенсор (G102/G203 сообщают диапазон до 8000 DPI; X11 поддерживает 50–26000, шаг 50, до 8 уровней).
- **Автоприменение** — каждое изменение сохраняется и уходит в мышь через короткую паузу; кнопки «Применить» нет.
- **Частота опроса** — 125 / 250 / 500 / 1000 Гц.
- **Подсветка** — статичная, «дыхание», цветовой цикл; цвет из пресетов, HEX или палитры; яркость и скорость.
- **Светлая, тёмная и системная темы** — переключаются в меню оформления или сегментом в разделе «Приложение»; выбор сохраняется.
- **Адаптивная раскладка** — на широком окне настройки и панель устройства/журнала стоят рядом, на узком — друг под другом.
- **Автозапуск и трей** — по желанию запускается при входе в Windows; закрытие окна сворачивает приложение в трей, а не завершает его.
- **Профиль** — `config.json` создаётся автоматически и повторно применяется при подключении мыши.
- **Диагностика** — журнал в интерфейсе и консольные режимы (`python device_backend.py`, `python hid_backend.py`, `python attack_shark_backend.py`).
- **Фирменное ПО не нужно** — G HUB и утилита Attack Shark не требуются.

> Уровни DPI хранятся в приложении и применяются по одному. У мышей Logitech приложение **не** перепрограммирует уровни, которые переключает физическая кнопка DPI, — они находятся в onboard-профиле мыши. У X11 пресеты записываются в слоты DPI устройства (до 8).

## Требования

- Windows 10/11 (проверено). Код переносим, но macOS/Linux не тестировались; на Linux могут понадобиться udev-правила для hidapi.
- Python 3.10+ (проверено на 3.10).
- Logitech G HUB должен быть **полностью закрыт**, включая иконку в трее, если используется мышь Logitech: он занимает тот же HID++ интерфейс. Утилиту Attack Shark тоже нужно закрыть при работе с X11.

## Установка

### Готовый exe

Скачайте **`G102LightsyncControl.exe`** из [последнего релиза](https://github.com/ste4ik/g102-lightsync-control/releases/latest) и запустите — Python не нужен. Профиль хранится в `%APPDATA%\G102 Lightsync Control\config.json`.

### Из исходников

```powershell
git clone https://github.com/ste4ik/g102-lightsync-control.git
cd g102-lightsync-control
python -m pip install -r requirements.txt
```

Вручную:

```powershell
python -m pip install hidapi PySide6-Essentials
```

Пакет **`hidapi`** (от trezor) — это Python-биндинг к hidapi; на Windows wheel содержит нативную библиотеку и устанавливает модуль с именем `hid`.

> Если раньше стоял пакет `hid` от apmorton (ctypes-обёртка, требующая отдельный `hidapi.dll`), его нужно удалить — он перекрывает рабочий модуль:
>
> ```powershell
> python -m pip uninstall hid -y
> python -m pip install hidapi
> ```

## Запуск

```powershell
python main.py
```

Либо двойным щелчком по `run.bat` (он переходит в свою папку, запускает приложение и оставляет окно открытым при ошибке).

При старте программа сама ищет поддерживаемую мышь и, если находит, подключается и применяет сохранённый профиль. Изменения в интерфейсе **применяются автоматически**: переключатели — через короткую паузу, ползунки — сразу после отпускания. Каждое изменение тут же сохраняется в `config.json`. Принудительно синхронизировать настройки можно через **«Устройство → Применить сейчас»** (`Ctrl+Enter`).

Закрытие окна (`X`) сворачивает приложение в трей, а не завершает его: щёлкните по иконке, чтобы вернуть окно, а для выхода используйте **«Выход»** в меню трея. Галочка **«Запускать при входе в Windows»** в разделе **«Приложение»** добавляет приложение в автозапуск.

### Поддерживаемые устройства

**Logitech (HID++ 2.0)**

| PID | Модель |
|---|---|
| `0xC084` | G102 / G203 Prodigy |
| `0xC092` | G102 / G203 Lightsync |
| `0xC093` | G102 Lightsync (вариант) |
| `0xC09D` | G102 Lightsync (новая ревизия) |

**Attack Shark X11 (вендорный HID, VID `0x1D57`)**

| PID | Подключение |
|---|---|
| `0xFA55` | USB-кабель |
| `0xFA60` | Приёмник 2.4 ГГц |

Название в интерфейсе берётся из product string самой мыши. Если подключено несколько поддерживаемых мышей, приоритет отдаётся последней использованной; кнопка «Подключить мышь» запускает повторный поиск.

## Конфигурация

`config.json` создаётся рядом с `main.py` при запуске из исходников. Готовый exe хранит его в `%APPDATA%\G102 Lightsync Control\config.json`. Отсутствующие или некорректные значения заменяются безопасными значениями по умолчанию.

```json
{
  "dpi": {
    "levels": [800, 1600, 3200],
    "active_level": 0
  },
  "polling_rate": 1000,
  "lighting": {
    "mode": "static",
    "color": "#00E5A0",
    "brightness": 100,
    "speed": 60
  },
  "app": {
    "autostart": false,
    "theme": "system",
    "last_device": ""
  }
}
```

| Поле | Назначение |
|---|---|
| `dpi.levels` | Список пресетов; значения ограничиваются 50–26000 и округляются до 50 (редактор сужает диапазон до сенсора подключённой мыши) |
| `dpi.active_level` | Индекс применяемого пресета |
| `polling_rate` | `125`, `250`, `500` или `1000` |
| `lighting.mode` | `static`, `breathing` или `cycle` |
| `lighting.color` | `#RRGGBB` |
| `lighting.brightness` | 1–100 |
| `lighting.speed` | 1–100 (только для breathing/cycle; static её игнорирует) |
| `app.autostart` | Дублирует запись в `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` |
| `app.theme` | `system`, `light` или `dark` |
| `app.last_device` | Последний успешно открытый backend (`logitech` или `attack_shark`), используется для выбора мыши, если подключены обе |

## Если мышь не находится

1. **Полностью закройте фирменное ПО** — G HUB (`lghub_agent`, `lghub_system_tray`) для Logitech и утилиту Attack Shark для X11.
2. Запустите диагностику без GUI:
   ```powershell
   python device_backend.py
   ```
   Она покажет все подключённые поддерживаемые мыши. Подробности — `python hid_backend.py` (Logitech) или `python attack_shark_backend.py` (X11): найденные HID-коллекции (PID, интерфейс, usage), диапазон DPI, текущую частоту опроса и состояние подсветки. Настройки они не меняют.
3. **«Access denied»** — закройте фирменную утилиту и/или запустите терминал от имени администратора.
4. Убедитесь, что установлен правильный модуль `hid` (см. примечание про `hidapi`).
5. У X11 используйте **USB-кабель или приёмник 2.4 ГГц** — Bluetooth не поддерживается. Переподключите мышь и нажмите «Подключить мышь».

## Как это работает

Все запросы — HID++ 2.0 long report (20 байт, report ID `0x11`, device index `0xFF`, функция `(fn << 4) | 0x0B`). На этой мыши HID++ идёт обычными output/input reports через `hidapi write()/read()`; feature reports (`send_feature_report`) не работают. Backend сам перебирает vendor-коллекции (`usage_page 0xFF00`) и оставляет ту, которая отвечает на запрос `IRoot → 0x2201`.

Индекс фичи ищется через `IRoot = 0x0000`, function `0x00`, параметры `[id_hi, id_lo, 0, 0]`; ответ — `[feature_index, type, version]`.

| Фича | Назначение | Используемые функции |
|---|---|---|
| `0x2201` | Adjustable DPI | `0` число сенсоров, `1` список DPI, `2` get, `3` set |
| `0x8060` | Adjustable Report Rate | `0` список, `1` get (мс), `2` set (мс) |
| `0x8071` | RGB Effects (Lightsync) | `0` info, `1` set cluster effect, `5` software control |
| `0x8070` | Color LED Effects (fallback) | `0` info, `1` zone info, `2` effect info, `3` set effect |
| `0x8100` | Onboard Profiles | `1` set mode, `2` get mode |

**Подсветка.** Перед установкой эффекта приложение переводит LED-контроллер под программное управление (`0x8071` fn `5`, параметры `01 03 05`). Пакеты эффектов:

```
Static:     [cluster, effect_index, R, G, B, 0×7, persistence=1]
Breathing:  [cluster, effect_index, R, G, B, period_hi, period_lo, 0, brightness, 0×3, persistence=1]
Cycle:      [cluster, effect_index, 0×5, period_hi, period_lo, brightness, 0×2, persistence=1]
Wave:       [cluster, effect_index, 0×6, period_hi, period_lo, direction, 0, persistence=1]
```

Период — big-endian миллисекунды (1000–8000, получаются из скорости в UI). Яркость 1–100; у Static отдельного поля яркости нет, поэтому масштабируется цвет. Протокольные ID эффектов из `getEffectInfo` — `0x01` static, `0x03` cycle, `0x04` wave, `0x0A` breathing; это не то же самое, что индексы эффектов внутри кластера (по умолчанию 1–4), которые приложение пытается определить автоматически и использует как fallback.

**Onboard-профиль.** Пока включён профиль из памяти мыши (`0x8100`, mode `0x01`), прошивка отклоняет смену частоты опроса (`0x8060` → `InvalidArgument`), потому что частота принадлежит профилю. Поэтому перед применением настроек приложение переключает мышь в host-режим (`0x8100` fn `1`, параметр `0x02`) — так же поступает G HUB. Это изменение состояния устройства, и оно сохраняется после выхода из программы.

### Протокол Attack Shark X11

X11 общается через вендорные HID **feature reports** (не HID++). Приложение открывает интерфейс 2 (`usage_page 0x0B`) для команд и держит открытой соответствующую interrupt-IN коллекцию (`usage_page 0x0A`) для чтения подтверждений. Длина отчётов у проводного и беспроводного вариантов немного различается.

| Отчёт | Назначение | Длина (wireless / wired) |
|---|---|---|
| `0x04` | Слоты DPI, активный слот, флаги сенсора | 56 / 51 |
| `0x05` | Режим подсветки, цвет, яркость, скорость | 15 / 13 |
| `0x06` | Частота опроса | 9 / 9 |
| `0xA0` | Разрешение на запись перед каждой командой | 8 / 8 |

- **Контрольные суммы** — отчёт DPI заканчивается 16-битной big-endian суммой байт 3–49, отчёт подсветки — суммой байт 3–10. В отчёте частоты используется однобайтовая инверсия (`byte[4] = ~byte[3]`).
- **Разрешение** — перед записью отправляется `0xA0` (8 байт), затем пауза 250 мс, чтение и проверка `byte[1] == 0x01`.
- **Подтверждение** — успешная запись подтверждается 5-байтовым событием `[0x03, device_id, 0x50, status, report_id]` на интерфейсе событий. Команды отправляются с паузами, чтобы не терять пакеты.
- **DPI** — сенсор PAW3311 использует таблицу с шагом 50. Слоты читаются, изменяются (только пресеты и активный слот) и записываются обратно, поэтому посторонние настройки — lift-off, ripple control, debounce — сохраняются.
- **Подсветка** — режим в старшем полубайте байта 3 (`0x1` static, `0x2` breathing, `0x3` neon/cycle), яркость 1–8, скорость LED 1–5, RGB в байтах 6–8. Буфер сначала читается, посторонние поля сохраняются.
- **Частота опроса** — `125 → 0x08`, `250 → 0x04`, `500 → 0x02`, `1000 → 0x01`.

Реализация протокола основана на [HarukaYamamoto0/attack-shark-x11-driver](https://github.com/HarukaYamamoto0/attack-shark-x11-driver/).

Ссылки:

- HID++ 2.0, feature `0x2201`: <https://www.lekensteyn.nl/files/logitech/x2201_adjustabledpi.html>
- Разбор протокола: <https://github.com/kasik96/opengcontrol/blob/main/docs/PROTOCOL.md>
- Референс Lightsync-пакетов: <https://github.com/smasty/g203-led>
- libratbag (`0x8071` / `0x8060`): <https://github.com/libratbag/libratbag>

## Структура проекта

```
G102_Lightsync_Control/
├── device_backend.py       # единый слой поиска и выбора поддерживаемых мышей
├── hid_backend.py          # Logitech HID++ 2.0: discovery, DPI, частота опроса, RGB
├── attack_shark_backend.py # вендорный HID-протокол Attack Shark X11
├── gui.py                  # PySide6 UI + темы + адаптивная раскладка + трей/автозапуск
├── main.py                 # точка входа
├── requirements.txt
├── build_exe.ps1     # сборка одного exe (PyInstaller)
├── run.bat           # запуск в Windows
├── assets/           # SVG мыши Lucide, галочки, готовые иконки приложения (PNG/ICO)
├── tools/            # make_icon.py, version_info.txt
├── LICENSE
└── README.md
```

`config.json`, `build/`, `dist/` и `__pycache__/` создаются локально и исключены из Git.

## Сборка exe

```powershell
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
```

Результат — `dist\G102LightsyncControl.exe`: один файл без консольного окна, с иконкой, Qt-рантаймом и встроенной папкой `assets/`. Готовая сборка хранит профиль в `%APPDATA%\G102 Lightsync Control\`.

## Ограничения

- Настройки записываются как **volatile** — приложение не пишет во флеш-память и не редактирует onboard-профили. После переподключения или перезагрузки профиль применяется заново (автоматически при подключении). У X11 слоты DPI являются частью профиля устройства, поэтому сами пресеты записываются в мышь.
- Приложение не отслеживает отключение мыши; после переподключения нажмите «Переподключить».
- Одновременная работа с G HUB или утилитой Attack Shark приводит к конфликтам и «миганию» подсветки.
- При смене DPI или частоты мышь может на секунду «дёрнуться» — это нормально.
- `0x8070` (legacy-подсветка) реализован только как базовый fallback и протестирован гораздо хуже, чем `0x8071`.
- Backend X11 написан по протоколу референсного драйвера и не проверялся на каждой ревизии прошивки. Через приложение X11 поддерживает только статичную подсветку, «дыхание» и неон (цветовой цикл), а яркость и скорость квантуются в шаги устройства 1–8 / 1–5.
- У X11 значения DPI выше 20 000 в референсном формате кодируются теми же байтами, что и обычные значения, поэтому прочитанное из устройства значение после переподключения может отличаться от пресета. Значения до 20 000 читаются точно (или с точностью до шага 50).
- Автотестов и CI пока нет.

## Участие в разработке

Issues и pull requests приветствуются. Если вы проверили приложение на другой ревизии G102/G203 или прошивке X11, на Linux или macOS — приложите вывод `python device_backend.py` и диагностику соответствующего backend: это самый полезный материал для разбора.

## Лицензия

[MIT](LICENSE) © авторы G102 Lightsync Control

Интерфейс работает на Qt через [PySide6](https://doc.qt.io/qtforpython-6/) (LGPLv3). Иконка мыши — [Lucide «mouse»](https://lucide.dev/icons/mouse) (ISC); атрибуция описана в [`assets/README.md`](assets/README.md). Иконка приложения собирается из этого SVG скриптом `tools/make_icon.py`. Реализация протокола Attack Shark X11 основана на [HarukaYamamoto0/attack-shark-x11-driver](https://github.com/HarukaYamamoto0/attack-shark-x11-driver/).
