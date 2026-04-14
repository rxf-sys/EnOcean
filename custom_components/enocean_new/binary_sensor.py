"""Binary sensor platform: physical EnOcean wall switches / push buttons."""

from __future__ import annotations

import logging
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    PLATFORM_SCHEMA,
    BinarySensorEntity,
)
from homeassistant.const import CONF_DEVICE_CLASS, CONF_ID, CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    DATA_DONGLE,
    DOMAIN,
    EVENT_BUTTON_PRESSED,
    RORG_RPS,
)
from .device import EnOceanDevice
from .helpers import ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Binary Sensor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the EnOcean binary sensor platform from YAML."""
    if DOMAIN not in hass.data or DATA_DONGLE not in hass.data[DOMAIN]:
        _LOGGER.error(
            "EnOcean dongle is not initialised. Configure it via the UI "
            "or add `enocean_new:` to configuration.yaml before defining "
            "binary_sensor entities."
        )
        return

    dev_id: List[int] = config[CONF_ID]
    name: str = config[CONF_NAME]
    device_class: Optional[str] = config.get(CONF_DEVICE_CLASS)

    async_add_entities([EnOceanBinarySensor(hass, dev_id, name, device_class)])


class EnOceanBinarySensor(EnOceanDevice, BinarySensorEntity):
    """Receive RPS telegrams from a physical wall switch / button."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        dev_id: List[int],
        name: str,
        device_class: Optional[str],
    ) -> None:
        EnOceanDevice.__init__(self, hass, dev_id, name)
        self._attr_name = name
        if device_class:
            self._attr_device_class = device_class
        self._attr_unique_id = "enocean_new_binary_" + "".join(
            f"{b:02x}" for b in self.dev_id
        )
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        self.dongle.remove_listener(self._packet_received)

    def _packet_received(self, packet: dict) -> None:
        if packet.get("sender_id") != self.dev_id:
            return
        if packet.get("rorg") != RORG_RPS:
            return

        data = packet.get("data") or []
        if not data:
            return

        which = data[0]
        status = packet.get("status", 0)
        # NU bit (0x10 in status) = 1 -> single button pressed
        # NU bit            = 0 -> button released (or multi-button)
        pressed = (status & 0x10) != 0 and which != 0x00

        _LOGGER.debug(
            "Binary sensor %s rx: data=0x%02X status=0x%02X pressed=%s",
            self._attr_name,
            which,
            status,
            pressed,
        )

        if self._attr_is_on != pressed:
            self._attr_is_on = pressed
            self.schedule_update_ha_state()

        # Always fire an event so automations can react to every press
        self.hass.bus.async_fire(
            EVENT_BUTTON_PRESSED,
            {
                "id": self.dev_id_str,
                "value": which,
                "status": status,
                "pressed": pressed,
            },
        )
