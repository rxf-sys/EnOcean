# Devices and sender IDs

Dongle: EnOcean USB 300, `/dev/serial/by-id/usb-EnOcean_GmbH_USB_300_DE_EOAQQB54-if00-port0`,
base ID `FF:C8:31:80` (valid senders `FF:C8:31:80` .. `FF:C8:31:FF`),
chip ID `05:A7:90:63`, firmware app 2.15.0.0 / api 2.6.9.0 (`GATEWAYCTRL`).

Ranges:

| Range                       | Use               |
| --------------------------- | ----------------- |
| `FF:C8:31:81` .. `…:8F`     | unused (legacy tests, may still be taught somewhere; avoid) |
| `FF:C8:31:90` .. `…:9F`     | SR-4 channels: actuator 13 → `90`–`93`, 14 → `94`–`97`, 15 → `98`–`9B` |
| `FF:C8:31:A0` .. `…:BF`     | MF-2 contacts: actuator n, contact c → `0xA0 + 2·(n−1) + (c−1)` (1.1 = `A0`, 1.2 = `A1`, 2.1 = `A2`, …, 16.2 = `BF`); one logical channel uses the `.1` ID |
| `FF:C8:31:C0` .. `…:DF`     | blinds (JRG-2): actuator n, motor m → `0xC0 + 2·(n−1) + (m−1)` (1.1 = `C0`, 1.2 = `C1`, 2.1 = `C2`, 2.2 = `C3`) |

Allocation:

| Sender ID     | Actuator / channel | Room     | Data bytes (ON / OFF) | Entity                    | Status |
| ------------- | ------------------ | -------- | --------------------- | ------------------------- | ------ |
| `FF:C8:31:90` | 13.1 (GN-A-R12V-SR-4) | Gäste-WC | `0x70` / `0x50`    | `switch.leuchte_gaste_wc` | taught, tested and in HA 14.11.2026 |

Wall switches (mirrored into HA via `wall_switches`):

| Wall switch ID | Room     | ON key / OFF key           | Mirrors                   | Status |
| -------------- | -------- | -------------------------- | ------------------------- | ------ |
| `00:24:55:01`  | Gäste-WC | `0x50` bottom / `0x70` top | `switch.leuchte_gaste_wc` | direction pushbutton (bottom = on, top = off) observed 14.11.2026; ID and codes to be confirmed from log |
