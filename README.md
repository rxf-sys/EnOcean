# EnOcean (New) — HACS Custom Integration for Home Assistant

A custom Home Assistant integration that fixes the long-standing **sender-ID
bug** in the upstream `enocean` Python library so that **OPUS GN-A-R12V-MF-2**
classic actuators (and similar RPS-controlled devices) can finally be driven
from Home Assistant via an EnOcean USB-300 dongle.

## Why this exists

* The native HA `enocean` integration can only **receive** RPS telegrams.
  Its `switch` / `light` platforms send 4BS / VLD telegrams that classic OPUS
  actuators completely ignore.
* `kridgo/ha_enocean_custom` tries to fix this but suffers from the same
  bug as the upstream `enocean` library: every outgoing radio packet has its
  sender address rewritten to the dongle's base ID (`05:A7:90:63`). All your
  actuators end up reacting to every command at the same time.
* This integration ships its **own minimal ESP3 implementation** in
  `dongle.py`. It does **not** depend on the `enocean` Python library, so the
  configured `sender_id` is transmitted **exactly as given**.

## Hardware tested

| Component              | Detail                                                        |
| ---------------------- | ------------------------------------------------------------- |
| Dongle                 | EnOcean USB 300 EASYFIT (USB id `05A7:9063`)                  |
| Dongle base-ID         | `05:A7:90:63` (valid sender range `05:A7:90:64 .. 05:A7:90:E2`) |
| Actuators              | OPUS GN-A-R12V-MF-2 (Art. 561.177) — DIN-rail relay actuators |
| Home Assistant         | HAOS 17.1, Core 2026.3.4                                      |

## Installation (HACS)

1. In HACS → Integrations → ⋮ → *Custom repositories*
2. Add this repository, category *Integration*
3. Install **EnOcean (New)** from the HACS list
4. Restart Home Assistant
5. *Settings → Devices & Services → Add integration → EnOcean (New)*
6. Pick the device path (the picker prefers `/dev/serial/by-id/usb-EnOcean_*`)

Alternative – manual install: copy `custom_components/enocean_new` into your
HA `config/custom_components/` directory.

## Configuration

The dongle is configured via the UI (config flow). All entities are configured
via YAML in `configuration.yaml`.

### Switch (OPUS light / power actuators)

```yaml
switch:
  - platform: enocean_new
    name: "Leuchte HWR"
    sender_id: [0x05, 0xA7, 0x90, 0x64]   # virtual rocker, must be in base_id..base_id+127
    receiver_id: [0x00, 0x22, 0x71, 0xE2] # actor's own ID (optional, for state feedback)

  - platform: enocean_new
    name: "Steckdose Werkbank"
    sender_id: [0x05, 0xA7, 0x90, 0x65]
```

### Cover (jalousie / blinds actuator)

```yaml
cover:
  - platform: enocean_new
    name: "Jalousie Wohnzimmer"
    sender_id: [0x05, 0xA7, 0x90, 0x70]
    receiver_id: [0x00, 0x22, 0x6F, 0x04]
```

### Binary sensor (physical wall switch / push button)

```yaml
binary_sensor:
  - platform: enocean_new
    name: "Wandschalter HWR"
    id: [0x00, 0x25, 0x21, 0xF6]
    device_class: vibration
```

A button press fires an HA event:

```yaml
event_type: enocean_new.button_pressed
event_data:
  id: "00:25:21:F6"
  value: 0x70
  pressed: true
```

### Sensor (temperature / humidity)

```yaml
sensor:
  - platform: enocean_new
    name: "Temperatur Wohnzimmer"
    id: [0x00, 0x01, 0xA2, 0x9A]
    device_class: temperature

  - platform: enocean_new
    name: "Feuchte Wohnzimmer"
    id: [0x00, 0x01, 0xA2, 0x9A]
    device_class: humidity
```

## Teach-In procedure (OPUS actuators)

1. Turn the OPUS actuator's selector to `LRN`.
2. In Home Assistant, **toggle the switch entity ON**.
3. The actuator's LED flashes briefly to confirm.
4. Turn the selector back to `AUTO`.

Each switch entity must use a **unique** `sender_id` from the dongle's
base-ID range (`base_id + 1 .. base_id + 127`). Two switch entities with the
same `sender_id` will control the same actuator.

## Sender-ID range

```
base_id  = [0x05, 0xA7, 0x90, 0x63]   # read from dongle on startup
device 1 = [0x05, 0xA7, 0x90, 0x64]
device 2 = [0x05, 0xA7, 0x90, 0x65]
...
device 127 = [0x05, 0xA7, 0x90, 0xE2]
```

The dongle's actual base ID is logged at INFO level on startup.

## Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.enocean_new: debug
```

You will see every transmitted and received ESP3 frame in the log.

## File layout

```
custom_components/enocean_new/
├── __init__.py        # Integration setup (YAML + config entry)
├── manifest.json      # HACS metadata
├── const.py           # Constants and packet type IDs
├── dongle.py          # ESP3 protocol implementation, base-ID readout
├── device.py          # Common entity helpers
├── switch.py          # OPUS switch / light actuators
├── cover.py           # OPUS jalousie actuators
├── binary_sensor.py   # Physical wall switches / push buttons
├── sensor.py          # Temperature / humidity sensors (4BS)
├── config_flow.py     # UI configuration of the dongle path
├── strings.json       # UI strings
└── translations/      # English + German translations
```
