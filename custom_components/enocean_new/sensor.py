"""Sensor platform: temperature/humidity sensors (4BS) and the EnOcean monitor."""

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
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import PlatformNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    DATA_DONGLE,
    DATA_KNOWN_IDS,
    DOMAIN,
    MONITOR_HISTORY,
    RORG_4BS,
)
from .device import EnOceanDevice, register_known_id
from .dongle import telegram_event_data
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
        # The dongle may still be starting (or retrying after the USB stick
        # appeared late); Home Assistant retries the platform setup.
        raise PlatformNotReady("EnOcean dongle is not initialised yet")

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
        register_known_id(self.hass, self.dev_id, self._attr_name)
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the EnOcean monitor for the dongle of this config entry."""
    async_add_entities([EnOceanMonitorSensor(hass)])


class EnOceanMonitorSensor(SensorEntity):
    """Shows the most recent received telegrams (state: last sender ID).

    Unknown sender IDs are marked so new wall switches or sensors can be
    identified from the dashboard instead of the log.
    """

    _attr_should_poll = False
    _attr_name = "EnOcean Monitor"
    _attr_unique_id = "enocean_new_monitor"
    _attr_icon = "mdi:radio-tower"
    # The telegram list changes with every telegram; keep it out of the
    # recorder. The state (last sender) still shows up in the logbook.
    _unrecorded_attributes = frozenset({"telegrams"})

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._telegrams: List[dict] = []

    async def async_added_to_hass(self) -> None:
        self.hass.data[DOMAIN][DATA_DONGLE].add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        dongle = self.hass.data.get(DOMAIN, {}).get(DATA_DONGLE)
        if dongle is not None:
            dongle.remove_listener(self._packet_received)

    @callback
    def _packet_received(self, packet: dict) -> None:
        entry = telegram_event_data(packet)
        known = self.hass.data[DOMAIN].get(DATA_KNOWN_IDS, {})
        entry["name"] = known.get(entry["sender_id"], "?")
        entry["time"] = dt_util.now().strftime("%d.%m. %H:%M:%S")
        self._telegrams.insert(0, entry)
        del self._telegrams[MONITOR_HISTORY:]
        self._attr_native_value = entry["sender_id"]
        self._attr_extra_state_attributes = {"telegrams": list(self._telegrams)}
        self.async_write_ha_state()
