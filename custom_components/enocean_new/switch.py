"""Switch platform for OPUS / EnOcean classic actuators (RPS-controlled).

Supports a ``channel`` parameter (0 or 1) that selects which virtual rocker
is used for ON/OFF.  This is critical for USB300 dongles whose firmware always
transmits with the base_id: the *channel* is then the only way to address
independent actuators from the same sender address.
"""

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
    CHANNEL_ON_OFF,
    CONF_CHANNEL,
    CONF_RECEIVER_ID,
    CONF_SENDER_ID,
    DATA_DONGLE,
    DOMAIN,
    OPUS_RELEASE,
    PRESS_RELEASE_DELAY,
    RORG_1BS,
    RORG_RPS,
    STATUS_PRESSED,
    STATUS_RELEASED,
)
from .device import EnOceanDevice
from .dongle import format_id
from .helpers import ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Switch"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENDER_ID): ENOCEAN_ID,
        vol.Optional(CONF_RECEIVER_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_CHANNEL, default=0): vol.In([0, 1]),
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
    channel: int = config[CONF_CHANNEL]

    dongle = hass.data[DOMAIN][DATA_DONGLE]
    if not dongle.is_valid_sender(sender_id):
        _LOGGER.warning(
            "Switch '%s' sender_id %s is outside the dongle's valid range "
            "(base_id .. base_id+127). The dongle will refuse to send.",
            name,
            format_id(sender_id),
        )

    async_add_entities(
        [EnOceanSwitch(hass, sender_id, receiver_id, name, channel)]
    )


class EnOceanSwitch(EnOceanDevice, SwitchEntity):
    """Representation of an OPUS-style switch driven via RPS telegrams."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        sender_id: List[int],
        receiver_id: Optional[List[int]],
        name: str,
        channel: int = 0,
    ) -> None:
        EnOceanDevice.__init__(self, hass, sender_id, name)
        self._sender_id: List[int] = [int(b) & 0xFF for b in sender_id]
        self._receiver_id: Optional[List[int]] = (
            [int(b) & 0xFF for b in receiver_id] if receiver_id else None
        )
        self._attr_name = name
        self._attr_is_on = False
        self._attr_assumed_state = self._receiver_id is None

        on_val, off_val = CHANNEL_ON_OFF.get(channel, CHANNEL_ON_OFF[0])
        self._on_value = on_val
        self._off_value = off_val
        self._channel = channel

        self._attr_unique_id = (
            "enocean_new_switch_"
            + "".join(f"{b:02x}" for b in self._sender_id)
            + f"_ch{channel}"
        )

    async def async_added_to_hass(self) -> None:
        """Register packet listener once entity is fully added."""
        if self._receiver_id is not None:
            self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        if self._receiver_id is not None:
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
            if value == self._on_value:
                self._update_state(True)
            elif value == self._off_value:
                self._update_state(False)
        elif rorg == RORG_1BS:
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
        self.dongle.send_rps_command(
            self._sender_id, button_value, status=STATUS_PRESSED
        )
        time.sleep(PRESS_RELEASE_DELAY)
        self.dongle.send_rps_command(
            self._sender_id, OPUS_RELEASE, status=STATUS_RELEASED
        )

    def turn_on(self, **kwargs) -> None:
        _LOGGER.debug(
            "Switch %s -> ON (sender_id=%s ch=%d on=0x%02X)",
            self._attr_name,
            self.dev_id_str,
            self._channel,
            self._on_value,
        )
        self._send_press_release(self._on_value)
        self._attr_is_on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        _LOGGER.debug(
            "Switch %s -> OFF (sender_id=%s ch=%d off=0x%02X)",
            self._attr_name,
            self.dev_id_str,
            self._channel,
            self._off_value,
        )
        self._send_press_release(self._off_value)
        self._attr_is_on = False
        self.schedule_update_ha_state()
