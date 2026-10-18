# G102 Lightsync Control

![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D4)
![License](https://img.shields.io/badge/license-MIT-2EE6A6)
![Protocol](https://img.shields.io/badge/protocol-HID%2B%2B%202.0-8B5CF6)

A lightweight, driver-free replacement for Logitech G HUB for the **G102 / G203 Lightsync** and **G203 Prodigy** gaming mice. It talks to the mouse directly over **HID++ 2.0** using hidapi — no kernel driver, no libusb, no replacement of the system HID driver.

The UI is built with **PySide6** (Qt 6) and follows the system light/dark appearance; the device layer uses `hidapi` (imported as `hid`).

> **Unofficial project.** Not affiliated with or endorsed by Logitech. Use at your own risk.

---

## Features

- **DPI** — unlimited app-side presets (200–8000, step 50), pick the active one.
- **Automatic apply** — every change is saved and sent to the mouse after a short pause; there is no Apply button.
- **Polling rate** — 125 / 250 / 500 / 1000 Hz.
- **Lighting** — Static, Breathing and Color Cycle; color via presets, HEX input or a color picker; brightness and speed control.
- **Saved profile** — `config.json` next to the app is created automatically and re-applied when the mouse reconnects.
- **Built-in diagnostics** — device log in the UI and a headless CLI (`python hid_backend.py`).
- **No G HUB required** — G HUB can be uninstalled entirely.

> DPI presets are stored in the app and applied individually. The app does **not** reprogram the levels the physical DPI button cycles through on the mouse — those live in the onboard profile.

---

## Requirements

- Windows 10/11 (tested) — the code itself is portable, but macOS/Linux are untested and may need hidapi permissions (udev rules).
- Python 3.10+ (tested on 3.10).
- Logitech G HUB **must be closed** (fully, including the tray icon) while this app runs. G HUB owns the same HID++ interface and will fight over the device.

## Installation

```powershell
git clone https://github.com/<your-username>/G102_Lightsync_Control.git
cd G102_Lightsync_Control
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

The app scans for the mouse on startup and, if found, connects and applies the saved profile automatically. Settings made in the UI are **applied automatically**: discrete changes after a short pause, sliders as soon as you release them. Every change is saved to `config.json` right away. If you ever need to force a sync, use **Устройство → Применить сейчас** (`Ctrl+Enter`).

### Supported devices

| USB PID | Model |
|---|---|
| `0xC084` | G102 / G203 Prodigy |
| `0xC092` | G102 / G203 Lightsync |
| `0xC093` | G102 Lightsync variant |
| `0xC09D` | G102 Lightsync (newer revision) |

The mouse identifies itself by its USB product string, so the UI shows the name reported by the device.

## Configuration

`config.json` is created next to `main.py` (and is ignored by Git). Missing or invalid values fall back to safe defaults.

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
  }
}
```

| Field | Meaning |
|---|---|
| `dpi.levels` | Preset list, each clamped to 200–8000 and rounded to a multiple of 50 |
| `dpi.active_level` | Index of the preset that is applied |
| `polling_rate` | One of `125`, `250`, `500`, `1000` |
| `lighting.mode` | `static`, `breathing` or `cycle` |
| `lighting.color` | `#RRGGBB` |
| `lighting.brightness` | 1–100 |
| `lighting.speed` | 1–100 (breathing/cycle only; static ignores it) |

## Troubleshooting

If the mouse is not detected or settings do not apply:

1. **Close G HUB completely** — check for `lghub_agent` and `lghub_system_tray` in Task Manager.
2. Run the headless diagnostic:
   ```powershell
   python hid_backend.py
   ```
   It lists every matching HID collection with PID, interface and usage, then prints the DPI range, current polling rate and discovered LED effects. It does not change any settings.
3. **"Access denied"** — close G HUB and/or run the terminal as Administrator.
4. Make sure the correct `hid` module is installed (see the `hidapi` note above).
5. Replug the mouse and press **Подключить мышь** in the app.

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

References:

- HID++ 2.0 Adjustable DPI: <https://www.lekensteyn.nl/files/logitech/x2201_adjustabledpi.html>
- Protocol write-up: <https://github.com/kasik96/opengcontrol/blob/main/docs/PROTOCOL.md>
- Working Lightsync packet reference: <https://github.com/smasty/g203-led>
- libratbag (`0x8071` / `0x8060`): <https://github.com/libratbag/libratbag>

## Project structure

```
G102_Lightsync_Control/
├── hid_backend.py    # HID++ 2.0: discovery, DPI, polling rate, RGB
├── gui.py            # PySide6 UI + auto-apply + config.json handling
├── main.py           # entry point
├── requirements.txt
├── run.bat           # Windows launcher
├── assets/           # Lucide mouse SVG + generated app icon (PNG/ICO)
├── tools/            # make_icon.py — regenerates the icon assets
├── LICENSE
└── README.md
```

`config.json` and `__pycache__/` are generated locally and ignored by Git.

## Limitations

- Settings are written as **volatile** — the app never writes to flash memory or edits onboard profiles. Reconnecting or rebooting requires re-applying the profile (which happens automatically on connect).
- The app does not watch for the mouse being unplugged; use **Переподключить** after replugging.
- Running alongside G HUB causes conflicts and flickering.
- The mouse may briefly stutter when the DPI or polling rate changes — this is normal.
- `0x8070` (legacy lighting) is implemented only as a basic fallback and is far less tested than `0x8071`.
- No automated tests or CI yet.

## Contributing

Issues and pull requests are welcome. If you test the app on another G102/G203 revision, Linux or macOS, please include the output of `python hid_backend.py` — it is the most useful diagnostic.

## License

[MIT](LICENSE) © G102 Lightsync Control authors

The UI runs on Qt via [PySide6](https://doc.qt.io/qtforpython-6/) (LGPLv3). The mouse icon is [Lucide “mouse”](https://lucide.dev/icons/mouse) (ISC); see [`assets/README.md`](assets/README.md) for attribution. The application icon is generated from that SVG by `tools/make_icon.py`.

---

# Русский

Лёгкая замена Logitech G HUB для мышей **G102 / G203 Lightsync** и **G203 Prodigy**. Работает напрямую по **HID++ 2.0** через hidapi — без драйверов, libusb и замены системного HID-драйвера.

> **Неофициальный проект**, не связан с Logitech. Используйте на свой риск.

## Возможности

- **DPI** — неограниченное число уровней-пресетов в приложении (200–8000, шаг 50) и выбор активного.
- **Автоприменение** — каждое изменение сохраняется и уходит в мышь через короткую паузу; кнопки «Применить» нет.
- **Частота опроса** — 125 / 250 / 500 / 1000 Гц.
- **Подсветка** — статичная, «дыхание», цветовой цикл; цвет из пресетов, HEX или палитры; яркость и скорость.
- **Профиль** — `config.json` создаётся автоматически рядом с программой и повторно применяется при подключении мыши.
- **Диагностика** — журнал в интерфейсе и консольный режим (`python hid_backend.py`).
- **G HUB не нужен** — его можно полностью удалить.

> Уровни DPI хранятся в приложении и применяются по одному. Приложение **не** перепрограммирует уровни, которые переключает физическая кнопка DPI, — они находятся в onboard-профиле мыши.

## Требования

- Windows 10/11 (проверено). Код переносим, но macOS/Linux не тестировались; на Linux могут понадобиться udev-правила для hidapi.
- Python 3.10+ (проверено на 3.10).
- Logitech G HUB должен быть **полностью закрыт**, включая иконку в трее: он занимает тот же HID++ интерфейс.

## Установка

```powershell
git clone https://github.com/<ваш-логин>/G102_Lightsync_Control.git
cd G102_Lightsync_Control
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

При старте программа сама ищет мышь и, если находит, подключается и применяет сохранённый профиль. Изменения в интерфейсе **применяются автоматически**: переключатели — через короткую паузу, ползунки — сразу после отпускания. Каждое изменение тут же сохраняется в `config.json`. Принудительно синхронизировать настройки можно через **«Устройство → Применить сейчас»** (`Ctrl+Enter`).

### Поддерживаемые устройства

| PID | Модель |
|---|---|
| `0xC084` | G102 / G203 Prodigy |
| `0xC092` | G102 / G203 Lightsync |
| `0xC093` | G102 Lightsync (вариант) |
| `0xC09D` | G102 Lightsync (новая ревизия) |

Название в интерфейсе берётся из product string самой мыши.

## Конфигурация

`config.json` создаётся рядом с `main.py` (и исключён из Git). Отсутствующие или некорректные значения заменяются безопасными значениями по умолчанию.

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
  }
}
```

| Поле | Назначение |
|---|---|
| `dpi.levels` | Список пресетов; значения ограничиваются 200–8000 и округляются до 50 |
| `dpi.active_level` | Индекс применяемого пресета |
| `polling_rate` | `125`, `250`, `500` или `1000` |
| `lighting.mode` | `static`, `breathing` или `cycle` |
| `lighting.color` | `#RRGGBB` |
| `lighting.brightness` | 1–100 |
| `lighting.speed` | 1–100 (только для breathing/cycle; static её игнорирует) |

## Если мышь не находится

1. **Полностью закройте G HUB** — проверьте процессы `lghub_agent` и `lghub_system_tray` в диспетчере задач.
2. Запустите диагностику без GUI:
   ```powershell
   python hid_backend.py
   ```
   Она покажет найденные HID-коллекции (PID, интерфейс, usage), диапазон DPI, текущую частоту опроса и доступные LED-эффекты. Настройки она не меняет.
3. **«Access denied»** — закройте G HUB и/или запустите терминал от имени администратора.
4. Убедитесь, что установлен правильный модуль `hid` (см. примечание про `hidapi`).
5. Переподключите мышь и нажмите «Подключить мышь».

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

Ссылки:

- HID++ 2.0, feature `0x2201`: <https://www.lekensteyn.nl/files/logitech/x2201_adjustabledpi.html>
- Разбор протокола: <https://github.com/kasik96/opengcontrol/blob/main/docs/PROTOCOL.md>
- Референс Lightsync-пакетов: <https://github.com/smasty/g203-led>
- libratbag (`0x8071` / `0x8060`): <https://github.com/libratbag/libratbag>

## Структура проекта

```
G102_Lightsync_Control/
├── hid_backend.py    # HID++ 2.0: discovery, DPI, частота опроса, RGB
├── gui.py            # PySide6 UI + автоприменение + работа с config.json
├── main.py           # точка входа
├── requirements.txt
├── run.bat           # запуск в Windows
├── assets/           # SVG мыши Lucide + готовые иконки приложения (PNG/ICO)
├── tools/            # make_icon.py — пересборка иконок
├── LICENSE
└── README.md
```

`config.json` и `__pycache__/` создаются локально и исключены из Git.

## Ограничения

- Настройки записываются как **volatile** — приложение не пишет во флеш-память и не редактирует onboard-профили. После переподключения или перезагрузки профиль применяется заново (автоматически при подключении).
- Приложение не отслеживает отключение мыши; после переподключения нажмите «Переподключить».
- Одновременная работа с G HUB приводит к конфликтам и «миганию» подсветки.
- При смене DPI или частоты мышь может на секунду «дёрнуться» — это нормально.
- `0x8070` (legacy-подсветка) реализован только как базовый fallback и протестирован гораздо хуже, чем `0x8071`.
- Автотестов и CI пока нет.

## Участие в разработке

Issues и pull requests приветствуются. Если вы проверили приложение на другой ревизии G102/G203, на Linux или macOS — приложите вывод `python hid_backend.py`, это самый полезный диагностический материал.

## Лицензия

[MIT](LICENSE) © авторы G102 Lightsync Control

Интерфейс работает на Qt через [PySide6](https://doc.qt.io/qtforpython-6/) (LGPLv3). Иконка мыши — [Lucide «mouse»](https://lucide.dev/icons/mouse) (ISC); атрибуция описана в [`assets/README.md`](assets/README.md). Иконка приложения собирается из этого SVG скриптом `tools/make_icon.py`.
