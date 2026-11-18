"""The EnOcean (New) integration.

This integration provides RPS (F6) send support for OPUS / EnOcean classic
actuators that the upstream Home Assistant `enocean` integration cannot drive.
The dongle driver intentionally bypasses the buggy upstream `enocean` Python
library so that the configured `sender_id` is transmitted unchanged.
"""

from __future__ import annotations

import logging
import time

import serial
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE, Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CHANNEL_ON_OFF,
    DATA_DONGLE,
    DATA_SEEN,
    DOMAIN,
    EVENT_TELEGRAM,
    SEEN_MAX_IDS,
    STATUS_PRESSED,
)
from .dongle import DongleError, EnOceanDongle, format_id, telegram_event_data
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

# Platforms set up from the config entry (YAML platforms are set up by HA).
ENTRY_PLATFORMS = [Platform.SENSOR]

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
        vol.Optional("data_byte"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=255)
        ),
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
        except (DongleError, serial.SerialException) as err:
            # Do not fail the whole integration: a UI config entry for the
            # same stick retries (ConfigEntryNotReady) and the entity
            # platforms wait for the dongle (PlatformNotReady).
            _LOGGER.error(
                "Failed to set up EnOcean dongle from YAML on %s: %s",
                device_path,
                err,
            )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry (UI)."""
    hass.data.setdefault(DOMAIN, {})
    device_path = entry.data[CONF_DEVICE]
    try:
        await _setup_dongle(hass, device_path)
    except (DongleError, serial.SerialException) as err:
        raise ConfigEntryNotReady(
            f"Failed to set up EnOcean dongle on {device_path}: {err}"
        ) from err
    await hass.config_entries.async_forward_entry_setups(entry, ENTRY_PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, ENTRY_PLATFORMS):
        return False
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

    seen: dict = hass.data[DOMAIN].setdefault(DATA_SEEN, {})

    @callback
    def _fire_telegram_event(packet: dict) -> None:
        """Publish every received telegram for automations and the monitor."""
        event_data = telegram_event_data(packet)
        sender = event_data["sender_id"]
        entry = seen.pop(sender, {"count": 0})
        now = dt_util.now()
        entry.update(
            rorg=event_data["rorg"],
            data=event_data["data"],
            dbm=event_data["dbm"],
            count=entry["count"] + 1,
            time=now.strftime("%d.%m. %H:%M"),
            timestamp=now.timestamp(),
        )
        seen[sender] = entry  # re-inserted: dict order = least recently seen first
        while len(seen) > SEEN_MAX_IDS:
            seen.pop(next(iter(seen)))
        hass.bus.async_fire(EVENT_TELEGRAM, event_data)

    dongle.add_listener(_fire_telegram_event)
    _LOGGER.info("EnOcean dongle ready on %s", device_path)

    _register_services(hass)


def _get_dongle(hass: HomeAssistant) -> EnOceanDongle:
    """Return the active dongle or raise a user-visible error."""
    dongle: EnOceanDongle | None = hass.data.get(DOMAIN, {}).get(DATA_DONGLE)
    if dongle is None:
        raise HomeAssistantError("EnOcean dongle is not initialised")
    return dongle


def _check_sender(dongle: EnOceanDongle, sender_id) -> None:
    """Raise a user-visible error if the dongle may not send with sender_id."""
    if not dongle.is_valid_sender(sender_id):
        raise HomeAssistantError(
            f"Sender ID {format_id(sender_id)} is not allowed for this dongle. "
            f"Valid: {dongle.sender_range_str()}"
        )


async def _run_dongle_job(hass: HomeAssistant, job) -> None:
    """Run a blocking dongle job and turn DongleError into a user-visible error."""
    try:
        await hass.async_add_executor_job(job)
    except DongleError as err:
        raise HomeAssistantError(str(err)) from err


def _register_services(hass: HomeAssistant) -> None:
    """Register integration-wide services."""
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RPS):
        return

    async def _async_handle_send_rps(call: ServiceCall) -> None:
        dongle = _get_dongle(hass)
        sender_id = call.data["sender_id"]
        data_byte = call.data["data_byte"]
        status = call.data["status"]
        press_release = call.data["press_release"]
        _check_sender(dongle, sender_id)

        def _do_send() -> None:
            if press_release:
                dongle.send_rps_press_release(sender_id, data_byte, status)
            else:
                dongle.send_rps_command(sender_id, data_byte, status=status)

        await _run_dongle_job(hass, _do_send)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_RPS,
        _async_handle_send_rps,
        schema=SERVICE_SEND_RPS_SCHEMA,
    )

    async def _async_handle_teach_in(call: ServiceCall) -> None:
        """Send a teach-in RPS telegram (press + release) for a specific channel."""
        dongle = _get_dongle(hass)
        sender_id = call.data["sender_id"]
        channel = call.data["channel"]
        on_val = call.data.get("data_byte", CHANNEL_ON_OFF[channel][0])
        _check_sender(dongle, sender_id)

        _LOGGER.warning(
            "TEACH-IN: Sending RPS press+release with sender_id=%s "
            "channel=%d data=0x%02X. The actuator must be in LRN mode.",
            format_id(sender_id),
            channel,
            on_val,
        )
        await _run_dongle_job(
            hass, lambda: dongle.send_rps_press_release(sender_id, on_val)
        )
        _LOGGER.warning(
            "TEACH-IN: Telegram acknowledged by the dongle for sender_id=%s. "
            "Check that ONLY the target actuator confirmed the teach-in.",
            format_id(sender_id),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TEACH_IN,
        _async_handle_teach_in,
        schema=SERVICE_TEACH_IN_SCHEMA,
    )

    async def _async_handle_test_sender(call: ServiceCall) -> None:
        """Send ON and OFF telegrams with two different sender_id offsets.

        Procedure:
        1. Teach ONE actuator with sender_id = base_id + offset_a, channel 0.
        2. Call this service.
        3. Watch: the actuator should react ONLY to "Test A" (ON, then OFF),
           NOT to "Test B".
        """
        dongle = _get_dongle(hass)
        if not dongle.base_id:
            raise HomeAssistantError("Base ID unknown, cannot compute offsets")

        base = int.from_bytes(bytes(dongle.base_id), "big")
        offset_a = call.data["sender_offset_a"]
        offset_b = call.data["sender_offset_b"]
        delay = call.data["delay"]

        sid_a = list((base + offset_a).to_bytes(4, "big"))
        sid_b = list((base + offset_b).to_bytes(4, "big"))
        on_val, off_val = CHANNEL_ON_OFF[0]

        _LOGGER.warning(
            "=== SENDER-ID TEST START ===\n"
            "  Test A: sender_id=%s (base+%d)\n"
            "  Test B: sender_id=%s (base+%d)\n"
            "  Each test sends ON, waits %ds, sends OFF.\n"
            "  Watch which actuators react to each test!",
            format_id(sid_a), offset_a,
            format_id(sid_b), offset_b,
            delay,
        )

        def _do_test() -> None:
            for label, sid in (("A", sid_a), ("B", sid_b)):
                _LOGGER.warning(
                    ">>> Test %s: ON with sender=%s", label, format_id(sid)
                )
                dongle.send_rps_press_release(sid, on_val)
                time.sleep(delay)
                _LOGGER.warning(
                    ">>> Test %s: OFF with sender=%s", label, format_id(sid)
                )
                dongle.send_rps_press_release(sid, off_val)
                time.sleep(delay)
            _LOGGER.warning("=== SENDER-ID TEST COMPLETE ===")

        await _run_dongle_job(hass, _do_test)

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
