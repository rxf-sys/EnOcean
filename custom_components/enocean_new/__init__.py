"""The EnOcean (New) integration.

This integration provides RPS (F6) send support for OPUS / EnOcean classic
actuators that the upstream Home Assistant `enocean` integration cannot drive.
The dongle driver intentionally bypasses the buggy upstream `enocean` Python
library so that the configured `sender_id` is transmitted unchanged.
"""

from __future__ import annotations

import logging
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    CHANNEL_ON_OFF,
    DATA_DONGLE,
    DOMAIN,
    OPUS_RELEASE,
    PRESS_RELEASE_DELAY,
    STATUS_PRESSED,
    STATUS_RELEASED,
)
from .dongle import EnOceanDongle, format_id
from .helpers import ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_DEVICE): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SERVICE_SEND_RPS = "send_rps"
SERVICE_TEACH_IN = "teach_in"
SERVICE_TEST_SENDER = "test_sender"

SERVICE_SEND_RPS_SCHEMA = vol.Schema(
    {
        vol.Required("sender_id"): ENOCEAN_ID,
        vol.Required("data_byte"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        vol.Optional("status", default=STATUS_PRESSED): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
        vol.Optional("press_release", default=True): cv.boolean,
    }
)

SERVICE_TEACH_IN_SCHEMA = vol.Schema(
    {
        vol.Required("sender_id"): ENOCEAN_ID,
        vol.Optional("channel", default=0): vol.In([0, 1]),
    }
)

SERVICE_TEST_SENDER_SCHEMA = vol.Schema(
    {
        vol.Optional("sender_offset_a", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=127)
        ),
        vol.Optional("sender_offset_b", default=1): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=127)
        ),
        vol.Optional("delay", default=3): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=30)
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the integration from YAML."""
    hass.data.setdefault(DOMAIN, {})

    if DOMAIN in config and CONF_DEVICE in config[DOMAIN]:
        device_path = config[DOMAIN][CONF_DEVICE]
        try:
            await _setup_dongle(hass, device_path)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "Failed to set up EnOcean dongle from YAML on %s: %s",
                device_path,
                err,
            )
            return False
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry (UI)."""
    hass.data.setdefault(DOMAIN, {})
    device_path = entry.data[CONF_DEVICE]
    try:
        await _setup_dongle(hass, device_path)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error(
            "Failed to set up EnOcean dongle on %s: %s", device_path, err
        )
        return False
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    dongle: EnOceanDongle | None = hass.data.get(DOMAIN, {}).pop(DATA_DONGLE, None)
    if dongle is not None:
        await hass.async_add_executor_job(dongle.disconnect)
    for svc in (SERVICE_SEND_RPS, SERVICE_TEACH_IN, SERVICE_TEST_SENDER):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
    return True


async def _setup_dongle(hass: HomeAssistant, device_path: str) -> None:
    """Open the serial connection to the EnOcean dongle (idempotent)."""
    if DATA_DONGLE in hass.data.get(DOMAIN, {}):
        _LOGGER.debug("Dongle already initialised, skipping")
        return

    dongle = EnOceanDongle(hass, device_path)
    await hass.async_add_executor_job(dongle.connect)
    hass.data[DOMAIN][DATA_DONGLE] = dongle
    _LOGGER.info("EnOcean dongle ready on %s", device_path)

    _register_services(hass)


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-wide services."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RPS):
        return

    async def _async_handle_send_rps(call: ServiceCall) -> None:
        dongle: EnOceanDongle | None = hass.data.get(DOMAIN, {}).get(DATA_DONGLE)
        if dongle is None:
            _LOGGER.error("send_rps: dongle is not initialised")
            return

        sender_id = call.data["sender_id"]
        data_byte = call.data["data_byte"]
        status = call.data["status"]
        press_release = call.data["press_release"]

        if not dongle.is_valid_sender(sender_id):
            _LOGGER.warning(
                "send_rps: sender_id %s is outside the dongle's valid "
                "range (base_id..base_id+127). The dongle will refuse to send.",
                format_id(sender_id),
            )

        def _do_send() -> None:
            dongle.send_rps_command(sender_id, data_byte, status=status)
            if press_release:
                time.sleep(PRESS_RELEASE_DELAY)
                dongle.send_rps_command(
                    sender_id, OPUS_RELEASE, status=STATUS_RELEASED
                )

        await hass.async_add_executor_job(_do_send)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RPS,
        _async_handle_send_rps,
        schema=SERVICE_SEND_RPS_SCHEMA,
    )

    async def _async_handle_teach_in(call: ServiceCall) -> None:
        """Send a teach-in RPS telegram (press + release) for a specific channel."""
        dongle: EnOceanDongle | None = hass.data.get(DOMAIN, {}).get(DATA_DONGLE)
        if dongle is None:
            _LOGGER.error("teach_in: dongle is not initialised")
            return

        sender_id = call.data["sender_id"]
        channel = call.data["channel"]
        on_val, off_val = CHANNEL_ON_OFF.get(channel, CHANNEL_ON_OFF[0])

        _LOGGER.warning(
            "TEACH-IN: Sending RPS press+release with sender_id=%s "
            "channel=%d (ON=0x%02X, OFF=0x%02X). "
            "Put your actuator in teach-in mode NOW, then call this service.",
            format_id(sender_id),
            channel,
            on_val,
            off_val,
        )

        if not dongle.is_valid_sender(sender_id):
            _LOGGER.error(
                "teach_in: sender_id %s is OUTSIDE the valid range. "
                "Use base_id (%s) + offset 0..127.",
                format_id(sender_id),
                format_id(dongle.base_id) if dongle.base_id else "unknown",
            )
            return

        def _do_teach() -> None:
            dongle.send_rps_command(
                sender_id, on_val, status=STATUS_PRESSED
            )
            time.sleep(PRESS_RELEASE_DELAY)
            dongle.send_rps_command(
                sender_id, OPUS_RELEASE, status=STATUS_RELEASED
            )

        await hass.async_add_executor_job(_do_teach)
        _LOGGER.warning(
            "TEACH-IN: Telegram sent for sender_id=%s channel=%d. "
            "Check if ONLY the target actuator confirmed the teach-in.",
            format_id(sender_id),
            channel,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEACH_IN,
        _async_handle_teach_in,
        schema=SERVICE_TEACH_IN_SCHEMA,
    )

    async def _async_handle_test_sender(call: ServiceCall) -> None:
        """Send test telegrams with two different sender_id offsets.

        This helps diagnose whether the USB300 dongle actually transmits
        with different sender addresses or always uses the base_id.

        Procedure:
        1. Un-teach all actuators first.
        2. Teach ONE actuator with sender_id = base_id + offset_a, channel 0.
        3. Call this service.
        4. Watch: the actuator should react ONLY to "Test A", NOT to "Test B".
        5. If it reacts to both → dongle replaces sender_id with base_id.
        """
        dongle: EnOceanDongle | None = hass.data.get(DOMAIN, {}).get(DATA_DONGLE)
        if dongle is None:
            _LOGGER.error("test_sender: dongle is not initialised")
            return

        if not dongle.base_id:
            _LOGGER.error("test_sender: base_id unknown, cannot compute offsets")
            return

        base = int.from_bytes(dongle.base_id, "big")
        offset_a = call.data["sender_offset_a"]
        offset_b = call.data["sender_offset_b"]
        delay = call.data["delay"]

        sid_a = list((base + offset_a).to_bytes(4, "big"))
        sid_b = list((base + offset_b).to_bytes(4, "big"))
        on_val = CHANNEL_ON_OFF[0][0]  # Rocker B ON

        _LOGGER.warning(
            "=== SENDER-ID TEST START ===\n"
            "  Test A: sender_id=%s (base+%d)\n"
            "  Test B: sender_id=%s (base+%d)\n"
            "  Delay between tests: %ds\n"
            "  Watch which actuators react to each test!",
            format_id(sid_a), offset_a,
            format_id(sid_b), offset_b,
            delay,
        )

        def _do_test() -> None:
            try:
                _LOGGER.warning(
                    ">>> Test A: Sending ON with sender=%s",
                    format_id(sid_a),
                )
                dongle.send_rps_command(
                    sid_a, on_val, status=STATUS_PRESSED
                )
                time.sleep(PRESS_RELEASE_DELAY)
                dongle.send_rps_command(
                    sid_a, OPUS_RELEASE, status=STATUS_RELEASED
                )
                _LOGGER.warning(
                    ">>> Test A DONE. Waiting %ds before Test B...", delay
                )
            except Exception:
                _LOGGER.exception("Test A FAILED")
                return

            time.sleep(delay)

            try:
                _LOGGER.warning(
                    ">>> Test B: Sending ON with sender=%s",
                    format_id(sid_b),
                )
                dongle.send_rps_command(
                    sid_b, on_val, status=STATUS_PRESSED
                )
                time.sleep(PRESS_RELEASE_DELAY)
                dongle.send_rps_command(
                    sid_b, OPUS_RELEASE, status=STATUS_RELEASED
                )
                _LOGGER.warning(">>> Test B DONE.")
            except Exception:
                _LOGGER.exception("Test B FAILED")
                return

            _LOGGER.warning("=== SENDER-ID TEST COMPLETE ===")

        await hass.async_add_executor_job(_do_test)

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_SENDER,
        _async_handle_test_sender,
        schema=SERVICE_TEST_SENDER_SCHEMA,
    )

    _LOGGER.debug(
        "Registered services: %s.%s, %s.%s, %s.%s",
        DOMAIN, SERVICE_SEND_RPS,
        DOMAIN, SERVICE_TEACH_IN,
        DOMAIN, SERVICE_TEST_SENDER,
    )
