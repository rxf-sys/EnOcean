# Devices and sender IDs

Dongle: EnOcean USB 300, `/dev/serial/by-id/usb-EnOcean_GmbH_USB_300_DE_EOAQQB54-if00-port0`,
base ID `FF:C8:31:80` (valid senders `FF:C8:31:80` .. `FF:C8:31:FF` and the chip ID).

Ranges:

| Range                       | Use               |
| --------------------------- | ----------------- |
| `FF:C8:31:81` .. `…:8F`     | unused (legacy tests, may still be taught somewhere; avoid) |
| `FF:C8:31:90` .. `…:BF`     | lights / switch channels |
| `FF:C8:31:C0` .. `…:DF`     | blinds (JRG-2)    |

Allocation:

| Sender ID     | Actuator / channel | Room     | Data bytes (ON / OFF) | Entity                    | Status |
| ------------- | ------------------ | -------- | --------------------- | ------------------------- | ------ |
| `FF:C8:31:90` | 13.1 (GN-A-R12V-SR-4) | Gäste-WC | `0x70` / `0x50`    | `switch.leuchte_gaste_wc` | taught and tested 14.11.2026 |
