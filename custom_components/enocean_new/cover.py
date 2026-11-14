"""Cover platform for EnOcean / OPUS jalousie actuators (RPS-controlled)."""

from __future__ import annotations

import logging
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_DOWN_DATA,
    CONF_RECEIVER_ID,
    CONF_SENDER_ID,
    CONF_UP_DATA,
    COVER_DOWN,
    COVER_UP,
    DATA_DONGLE,
    DOMAIN,
)
from .device import EnOceanDevice
from .dongle import DongleError, format_id
from .helpers import DATA_BYTE, ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Cover"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENDER_ID): ENOCEAN_ID,
        vol.Optional(CONF_RECEIVER_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_UP_DATA, default=COVER_UP): DATA_BYTE,
        vol.Optional(CONF_DOWN_DATA, default=COVER_DOWN): DATA_BYTE,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: Optional[DiscoveryInfoType] = None,
) -> None:
    """Set up the EnOcean cover platform from YAML."""
    if DOMAIN not in hass.data or DATA_DONGLE not in hass.data[DOMAIN]:
        _LOGGER.error(
            "EnOcean dongle is not initialised. Configure it via the UI "
            "or add `enocean_new:` to configuration.yaml before defining "
            "cover entities."
        )
        return

    sender_id: List[int] = config[CONF_SENDER_ID]
    receiver_id: Optional[List[int]] = config.get(CONF_RECEIVER_ID)
    name: str = config[CONF_NAME]

    dongle = hass.data[DOMAIN][DATA_DONGLE]
    if not dongle.is_valid_sender(sender_id):
        _LOGGER.error(
            "Cover '%s' not created: sender_id %s is not allowed for this "
            "dongle. Valid: %s",
            name,
            format_id(sender_id),
            dongle.sender_range_str(),
        )
        return

    async_add_entities(
        [
            EnOceanCover(
                hass,
                sender_id,
                receiver_id,
                name,
                config[CONF_UP_DATA],
                config[CONF_DOWN_DATA],
            )
        ]
    )


class EnOceanCover(EnOceanDevice, CoverEntity):
    """OPUS jalousie cover driven via RPS telegrams."""

    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        hass: HomeAssistant,
        sender_id: List[int],
        receiver_id: Optional[List[int]],
        name: str,
        up_value: int,
        down_value: int,
    ) -> None:
        EnOceanDevice.__init__(self, hass, sender_id, name)
        self._up_value = up_value
        self._down_value = down_value
        self._sender_id: List[int] = [int(b) & 0xFF for b in sender_id]
        self._receiver_id: Optional[List[int]] = (
            [int(b) & 0xFF for b in receiver_id] if receiver_id else None
        )
        self._attr_name = name
        self._attr_is_closed: Optional[bool] = None
        self._attr_is_opening = False
        self._attr_is_closing = False
        # OPUS jalousies don't reliably report state, so HA should
        # show this entity's state as assumed.
        self._attr_assumed_state = True
        self._last_direction: Optional[int] = None
        self._attr_unique_id = "enocean_new_cover_" + "".join(
            f"{b:02x}" for b in self._sender_id
        )

    async def async_added_to_hass(self) -> None:
        if self._receiver_id is not None:
            self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        if self._receiver_id is not None:
            self.dongle.remove_listener(self._packet_received)

    def _packet_received(self, packet: dict) -> None:
        """Best-effort feedback handler; OPUS jalousies usually send nothing."""
        if not self._receiver_id:
            return
        if packet.get("sender_id") != self._receiver_id:
            return
        # Just log - state inference for OPUS jalousie is unreliable.
        _LOGGER.debug(
            "Cover %s received feedback packet: %s",
            self._attr_name,
            packet,
        )

    # ------------------------------------------------------------------ #
    # TX
    # ------------------------------------------------------------------ #
    def _send_press_release(self, button_value: int) -> None:
        try:
            self.dongle.send_rps_press_release(self._sender_id, button_value)
        except DongleError as err:
            raise HomeAssistantError(
                f"{self._attr_name}: sending failed: {err}"
            ) from err

    def open_cover(self, **kwargs) -> None:
        _LOGGER.debug(
            "Cover %s -> OPEN (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(self._up_value)
        self._last_direction = self._up_value
        self._attr_is_closed = False
        self._attr_is_opening = True
        self._attr_is_closing = False
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs) -> None:
        _LOGGER.debug(
            "Cover %s -> CLOSE (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(self._down_value)
        self._last_direction = self._down_value
        self._attr_is_closed = True
        self._attr_is_opening = False
        self._attr_is_closing = True
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs) -> None:
        """Stop the cover by sending another short pulse on the same channel."""
        _LOGGER.debug(
            "Cover %s -> STOP (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        # A press in the direction of travel stops the actuator. Without a
        # known direction a press would start a movement, so do nothing.
        if self._last_direction is None:
            _LOGGER.warning(
                "Cover %s: no direction sent since start, cannot stop",
                self._attr_name,
            )
            return
        self._send_press_release(self._last_direction)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.schedule_update_ha_state()
