"""Switch platform for OPUS / EnOcean classic actuators (RPS-controlled)."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_RECEIVER_ID,
    CONF_SENDER_ID,
    DATA_DONGLE,
    DOMAIN,
    OPUS_OFF,
    OPUS_ON,
    OPUS_RELEASE,
    PRESS_RELEASE_DELAY,
    RORG_1BS,
    RORG_RPS,
    STATUS_PRESSED,
    STATUS_RELEASED,
)
from .device import EnOceanDevice

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Switch"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENDER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_RECEIVER_ID): vol.All(cv.ensure_list, [vol.Coerce(int)]),
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the EnOcean switch platform from YAML."""
    if DOMAIN not in hass.data or DATA_DONGLE not in hass.data[DOMAIN]:
        _LOGGER.error(
            "EnOcean dongle is not initialised. Configure it via the UI "
            "or add `enocean_new:` to configuration.yaml before defining "
            "switch entities."
        )
        return

    sender_id: List[int] = config[CONF_SENDER_ID]
    receiver_id: Optional[List[int]] = config.get(CONF_RECEIVER_ID)
    name: str = config[CONF_NAME]

    async_add_entities([EnOceanSwitch(hass, sender_id, receiver_id, name)])


class EnOceanSwitch(EnOceanDevice, SwitchEntity):
    """Representation of an OPUS-style switch driven via RPS telegrams."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        sender_id: List[int],
        receiver_id: Optional[List[int]],
        name: str,
    ) -> None:
        EnOceanDevice.__init__(self, hass, sender_id, name)
        self._sender_id: List[int] = [int(b) & 0xFF for b in sender_id]
        self._receiver_id: Optional[List[int]] = (
            [int(b) & 0xFF for b in receiver_id] if receiver_id else None
        )
        self._attr_name = name
        self._attr_is_on = False
        self._attr_unique_id = "enocean_new_switch_" + "".join(
            f"{b:02x}" for b in self._sender_id
        )

    async def async_added_to_hass(self) -> None:
        """Register packet listener once entity is fully added."""
        self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        self.dongle.remove_listener(self._packet_received)

    # ------------------------------------------------------------------ #
    # RX
    # ------------------------------------------------------------------ #
    def _packet_received(self, packet: dict) -> None:
        """Handle status feedback from the actor (if any)."""
        if not self._receiver_id:
            return
        if packet.get("sender_id") != self._receiver_id:
            return

        rorg = packet.get("rorg")
        data = packet.get("data") or []
        if not data:
            return

        if rorg == RORG_RPS:
            value = data[0]
            if value == OPUS_ON:
                self._update_state(True)
            elif value == OPUS_OFF:
                self._update_state(False)
        elif rorg == RORG_1BS:
            # 1BS contact: bit 0 = state
            self._update_state(bool(data[0] & 0x01))

    def _update_state(self, is_on: bool) -> None:
        if self._attr_is_on != is_on:
            _LOGGER.debug(
                "Switch %s feedback: %s", self._attr_name, "ON" if is_on else "OFF"
            )
            self._attr_is_on = is_on
            self.schedule_update_ha_state()

    # ------------------------------------------------------------------ #
    # TX
    # ------------------------------------------------------------------ #
    def _send_press_release(self, button_value: int) -> None:
        """Send press-then-release telegrams using the configured sender_id."""
        # Press telegram
        self.dongle.send_rps_command(
            self._sender_id, button_value, status=STATUS_PRESSED
        )
        time.sleep(PRESS_RELEASE_DELAY)
        # Release telegram
        self.dongle.send_rps_command(
            self._sender_id, OPUS_RELEASE, status=STATUS_RELEASED
        )

    def turn_on(self, **kwargs) -> None:
        _LOGGER.debug(
            "Switch %s -> ON (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(OPUS_ON)
        self._attr_is_on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        _LOGGER.debug(
            "Switch %s -> OFF (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(OPUS_OFF)
        self._attr_is_on = False
        self.schedule_update_ha_state()
