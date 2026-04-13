"""The EnOcean (New) integration.

This integration provides RPS (F6) send support for OPUS / EnOcean classic
actuators that the upstream Home Assistant `enocean` integration cannot drive.
The dongle driver intentionally bypasses the buggy upstream `enocean` Python
library so that the configured `sender_id` is transmitted unchanged.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import DATA_DONGLE, DOMAIN
from .dongle import EnOceanDongle

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
