"""Base class shared by all EnOcean (New) entity platforms."""

from __future__ import annotations

import logging
from typing import List

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    DATA_DEVICES,
    DATA_DONGLE,
    DATA_KNOWN_IDS,
    DOMAIN,
    SIGNAL_DEVICES_UPDATED,
)
from .dongle import EnOceanDongle, format_id

_LOGGER = logging.getLogger(__name__)


def device_row(
    dev_id, kind: str, role: str, label: str, codes: str = ""
) -> dict:
    """Describe one EnOcean ID used by an entity (see register_device)."""
    return {
        "id": format_id(dev_id),
        "kind": kind,
        "role": role,
        "label": label,
        "codes": codes,
    }


def register_device(
    hass: HomeAssistant,
    entity_id: str,
    name: str,
    actuator: str | None,
    rows: List[dict],
) -> None:
    """Publish the EnOcean IDs of an entity for the device list and monitor."""
    data = hass.data.setdefault(DOMAIN, {})
    known = data.setdefault(DATA_KNOWN_IDS, {})
    for row in rows:
        row.update(name=name, entity_id=entity_id, actuator=actuator or "")
        known[row["id"]] = row["label"]
    data.setdefault(DATA_DEVICES, {})[entity_id] = rows
    async_dispatcher_send(hass, SIGNAL_DEVICES_UPDATED)


def unregister_device(hass: HomeAssistant, entity_id: str) -> None:
    """Remove an entity from the device list."""
    data = hass.data.get(DOMAIN, {})
    devices = data.get(DATA_DEVICES, {})
    devices.pop(entity_id, None)
    # Rebuild: another entity may use the same ID (e.g. temperature and
    # humidity of one sensor).
    data[DATA_KNOWN_IDS] = {
        row["id"]: row["label"] for rows in devices.values() for row in rows
    }
    async_dispatcher_send(hass, SIGNAL_DEVICES_UPDATED)


class EnOceanDevice:
    """Common helpers for EnOcean entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        dev_id: List[int],
        dev_name: str,
    ) -> None:
        self.hass = hass
        self.dev_id: List[int] = [int(b) & 0xFF for b in dev_id]
        self.dev_name = dev_name

    @property
    def dongle(self) -> EnOceanDongle:
        """Return the active dongle from hass.data."""
        return self.hass.data[DOMAIN][DATA_DONGLE]

    @property
    def dev_id_str(self) -> str:
        """Return a human readable representation of dev_id."""
        return format_id(self.dev_id)

    def _packet_received(self, packet: dict) -> None:  # pragma: no cover
        """Override in subclasses to react to received radio packets."""
