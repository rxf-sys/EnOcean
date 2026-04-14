"""Sensor platform: temperature and humidity sensors (4BS / A5)."""

from __future__ import annotations

import logging
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    CONF_DEVICE_CLASS,
    CONF_ID,
    CONF_NAME,
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    DATA_DONGLE,
    DOMAIN,
    RORG_4BS,
)
from .device import EnOceanDevice
from .helpers import ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Sensor"

DEVICE_CLASS_TEMPERATURE = "temperature"
DEVICE_CLASS_HUMIDITY = "humidity"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_DEVICE_CLASS, default=DEVICE_CLASS_TEMPERATURE): vol.In(
            [DEVICE_CLASS_TEMPERATURE, DEVICE_CLASS_HUMIDITY]
        ),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the EnOcean sensor platform from YAML."""
    if DOMAIN not in hass.data or DATA_DONGLE not in hass.data[DOMAIN]:
        _LOGGER.error(
            "EnOcean dongle is not initialised. Configure it via the UI "
            "or add `enocean_new:` to configuration.yaml before defining "
            "sensor entities."
        )
        return

    dev_id: List[int] = config[CONF_ID]
    name: str = config[CONF_NAME]
    device_class: str = config[CONF_DEVICE_CLASS]

    async_add_entities([EnOceanSensor(hass, dev_id, name, device_class)])


class EnOceanSensor(EnOceanDevice, SensorEntity):
    """Temperature or humidity sensor decoded from a 4BS (A5) telegram."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hass: HomeAssistant,
        dev_id: List[int],
        name: str,
        device_class: str,
    ) -> None:
        EnOceanDevice.__init__(self, hass, dev_id, name)
        self._attr_name = name
        self._kind = device_class
        self._attr_unique_id = (
            "enocean_new_sensor_"
            + device_class
            + "_"
            + "".join(f"{b:02x}" for b in self.dev_id)
        )
        if device_class == DEVICE_CLASS_TEMPERATURE:
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif device_class == DEVICE_CLASS_HUMIDITY:
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        self.dongle.remove_listener(self._packet_received)

    def _packet_received(self, packet: dict) -> None:
        if packet.get("sender_id") != self.dev_id:
            return
        if packet.get("rorg") != RORG_4BS:
            return
        data = packet.get("data") or []
        if len(data) < 4:
            return

        # A5-04-01 / A5-04-02 humidity + temperature profile:
        #   data[0] = unused
        #   data[1] = humidity (0..250 -> 0..100 %)
        #   data[2] = temperature (0..250 -> 0..40 °C)
        #   data[3] = status flags
        if self._kind == DEVICE_CLASS_TEMPERATURE:
            value = round(data[2] * 40.0 / 250.0, 1)
        elif self._kind == DEVICE_CLASS_HUMIDITY:
            value = round(data[1] * 100.0 / 250.0, 1)
        else:
            return

        _LOGGER.debug(
            "Sensor %s (%s) -> %s",
            self._attr_name,
            self._kind,
            value,
        )
        self._attr_native_value = value
        self.schedule_update_ha_state()
