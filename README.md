# EnOcean (New) — HACS Custom Integration for Home Assistant

A custom Home Assistant integration that sends **RPS (F6-02) rocker
telegrams** through an EnOcean USB300 dongle, so that classic,
rocker-controlled actuators such as **OPUS greenNet GN-A-R12V-MF-2** can be
driven from Home Assistant.

## Why this exists

* The native HA `enocean` integration can only **receive** RPS telegrams.
  Its `switch` / `light` platforms send D2-01 VLD / A5-38-08 telegrams that
  classic OPUS / Eltako Series-12 actuators ignore.
* This integration ships its **own minimal ESP3 implementation** in
  `dongle.py` (no dependency on the `enocean` Python library). The configured
  `sender_id` is transmitted exactly as given, and the dongle's RESPONSE to
  every telegram is checked, so a rejected telegram shows up as an error in
  Home Assistant instead of failing silently.

## Hardware tested

| Component       | Detail                                                                 |
| --------------- | ---------------------------------------------------------------------- |
| Dongle          | EnOcean USB 300 (FTDI, USB id `0403:6015`), base ID `FF:C8:31:80`      |
| Radio receiver  | OPUS antenna module GN-E-R12V-AM (561.151) on the greenNet RS485 bus   |
| Actuators       | OPUS GN-A-R12V-SR-4 (561.152) 4-channel switch, GN-A-R12V-JRG-2 (561.153) blinds; RS485 bus actuators without own radio |
| Home Assistant  | HAOS in a Proxmox VM, Core 2026.5.4                                    |

The OPUS REG actuators receive radio telegrams only through the antenna
module and **never send a status telegram**. Their state in Home Assistant is
therefore always *assumed* (optimistic).

## Installation (HACS)

1. In HACS → Integrations → ⋮ → *Custom repositories*
2. Add this repository, category *Integration*
3. Install **EnOcean (New)** from the HACS list
4. Restart Home Assistant
5. *Settings → Devices & Services → Add integration → EnOcean (New)*
6. Pick the device path (the picker prefers `/dev/serial/by-id/usb-EnOcean_*`)

Alternative – manual install: copy `custom_components/enocean_new` into your
HA `config/custom_components/` directory.

Keep the UI config entry even if the dongle is also set in YAML: if the stick
is not ready at boot (e.g. late USB passthrough in a VM), the config entry
retries automatically and the entities are created once the dongle answers.

**Only one program may use the stick.** Stop and disable autostart of any
other EnOcean add-on (e.g. an EnOcean MQTT bridge) and remove the core
`enocean` integration if it uses the same dongle. Otherwise the dongle does
not answer and setup fails with a hint to that effect.

## Sender IDs

On startup the integration logs (INFO level):

```
EnOcean dongle base_id: FF:C8:31:80  Valid sender range: FF:C8:31:80 .. FF:C8:31:FF (128 addresses)
EnOcean dongle firmware: app=... api=... chip=xx:xx:xx:xx description='...'
```

A USB300 may only transmit with its **chip ID** or one of the **128 IDs
starting at its base ID**. A base ID is always in `FF:80:00:00 ..
FF:FF:FF:80` and a multiple of 128. Entities and service calls with any other
sender ID are refused.

* Give every actuator channel its own sender ID. The allocation used in this
  installation is kept in [`docs/devices.md`](docs/devices.md).
* Never write a new base ID to the dongle: it can only be changed about 10
  times, and every actuator would have to be taught again.
* A replacement dongle has a different base ID, so all actuators must be
  taught again.

## Configuration

The dongle is configured via the UI (config flow) or YAML. Entities are
configured via YAML in `configuration.yaml`.

### Switch (OPUS light / power actuators)

```yaml
switch:
  - platform: enocean_new
    name: "Leuchte HWR"
    sender_id: [0xFF, 0xC8, 0x31, 0x81]   # base + 1, unique per actuator
    channel: 0                            # 0 = rocker B (default), 1 = rocker A
```

| Option        | Default                     | Meaning                                   |
| ------------- | --------------------------- | ----------------------------------------- |
| `sender_id`   | –                           | virtual rocker ID (chip ID or base + 0..127) |
| `channel`     | `0`                         | rocker for the default data bytes         |
| `on_data`     | `0x50` (ch 0) / `0x10` (ch 1) | data byte sent for ON                   |
| `off_data`    | `0x70` (ch 0) / `0x30` (ch 1) | data byte sent for OFF                  |
| `receiver_id` | –                           | actuator ID for status feedback, only for actuators that send one |

Rocker keys (EEP F6-02): `0x30` = A0 (left top), `0x10` = AI (left bottom),
`0x70` = B0 (right top), `0x50` = BI (right bottom). If ON and OFF are the
wrong way round for an actuator, swap them with `on_data` / `off_data`.

### Cover (jalousie / blinds actuator)

```yaml
cover:
  - platform: enocean_new
    name: "Jalousie Wohnzimmer"
    sender_id: [0xFF, 0xC8, 0x31, 0x90]
    up_data: 0x70     # default: B0 (rocker B top)
    down_data: 0x50   # default: BI (rocker B bottom)
```

*Stop* repeats the last direction (the actuator stops on a press in its
direction of travel). Without a known direction, stop does nothing.

### Binary sensor (physical wall switch / push button)

```yaml
binary_sensor:
  - platform: enocean_new
    name: "Wandschalter HWR"
    id: [0x00, 0x25, 0x21, 0xF6]
    device_class: power
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

## Teach-in procedure

In LRN mode an actuator stores the very next telegram it receives (a window
contact sending at that moment would be learned too). Prepare the service call
before switching to LRN and send it right away. Teaching adds a sender; it
does not remove the wall switches already taught.

### OPUS GN-A-R12V-SR-4 (561.152, 4-channel switch actuator) — verified

Each channel is taught separately, ON and OFF as two steps (direction
pushbutton). Note the positions of all three rotary switches first.

| Step | Lower switch | Upper switch | Middle switch | Action (`enocean_new.send_rps`) | LED |
| ---- | ------------ | ------------ | ------------- | ------------------------------- | --- |
| ON   | channel 1–4  | `0`          | `LRN`         | `data_byte: 0x70`               | flashes, then off |
| OFF  | same channel | `2`          | `AUTO` → `LRN`| `data_byte: 0x50`               | flashes, then off |
| Done | `AUTO`       | noted position | `AUTO`      | –                               | –   |

`0` is the stop directly left of `2` on the upper (EW) scale. Configure the
switch entity with `on_data: 0x70` and `off_data: 0x50`.

To remove a wrongly taught sender from one channel: lower switch to that
channel, middle switch to `CLR`, send the same telegram once.

### Other actuators

Set the teach-in function according to the actuator's manual, middle switch to
`LRN`, send the telegram, then return all switches to their previous
positions. Test ON / OFF and check that no other actuator reacts.

`enocean_new.test_sender` sends ON/OFF from two different offsets to verify
that an actuator reacts only to its own sender ID.

## Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.enocean_new: debug
```

You will see every transmitted and received ESP3 frame in the log.

## Tests

```
python -m unittest discover -s tests
```

The tests simulate the serial port and need neither Home Assistant nor
pyserial.

## File layout

```
custom_components/enocean_new/
├── __init__.py        # Integration setup (YAML + config entry), services
├── manifest.json      # HACS metadata
├── const.py           # Constants, packet types, return codes
├── dongle.py          # ESP3 protocol, acknowledged sending, base/chip ID readout
├── device.py          # Common entity helpers
├── helpers.py         # Shared config validators
├── switch.py          # OPUS switch / light actuators
├── cover.py           # OPUS jalousie actuators
├── binary_sensor.py   # Physical wall switches / push buttons
├── sensor.py          # Temperature / humidity sensors (4BS)
├── config_flow.py     # UI configuration of the dongle path
├── services.yaml      # send_rps, teach_in, test_sender
├── strings.json       # UI strings
└── translations/      # English + German translations
tests/
└── test_dongle.py     # ESP3 driver tests (serial port simulated)
```
