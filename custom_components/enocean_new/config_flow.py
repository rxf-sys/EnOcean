"""Config flow for the EnOcean (New) integration."""

from __future__ import annotations

import os
from typing import Any, List

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN


def _list_serial_devices() -> List[str]:
    """Return likely candidates for an EnOcean dongle.

    EnOcean USB-300 device paths show up in /dev/serial/by-id with
    "EnOcean" in the filename.
    """
    paths: List[str] = []
    by_id = "/dev/serial/by-id"
    if os.path.isdir(by_id):
        for entry in sorted(os.listdir(by_id)):
            full = os.path.join(by_id, entry)
            paths.append(full)
    # Sort: any path containing "enocean" first
    paths.sort(key=lambda p: 0 if "enocean" in p.lower() else 1)
    # Common fallback paths
    for default in ("/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyAMA0"):
        if os.path.exists(default) and default not in paths:
            paths.append(default)
    return paths


class EnOceanConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EnOcean (New)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show the device picker / accept manual input."""
        errors: dict[str, str] = {}

        devices = await self.hass.async_add_executor_job(_list_serial_devices)

        if user_input is not None:
            device_path = user_input[CONF_DEVICE]
            await self.async_set_unique_id(device_path)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"EnOcean ({os.path.basename(device_path)})",
                data={CONF_DEVICE: device_path},
            )

        if devices:
            schema = vol.Schema(
                {vol.Required(CONF_DEVICE, default=devices[0]): vol.In(devices)}
            )
        else:
            schema = vol.Schema({vol.Required(CONF_DEVICE): str})

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Handle YAML import."""
        return await self.async_step_user(import_data)
