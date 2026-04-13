"""Base class shared by all EnOcean (New) entity platforms."""

from __future__ import annotations

import logging
from typing import List

from homeassistant.core import HomeAssistant

from .const import DATA_DONGLE, DOMAIN
from .dongle import EnOceanDongle, format_id

_LOGGER = logging.getLogger(__name__)


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
