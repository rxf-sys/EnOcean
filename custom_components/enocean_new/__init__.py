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
    if hass.services.has_service(DOMAIN, SERVICE_SEND_RPS):
        hass.services.async_remove(DOMAIN, SERVICE_SEND_RPS)
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
    _LOGGER.debug("Registered service %s.%s", DOMAIN, SERVICE_SEND_RPS)
