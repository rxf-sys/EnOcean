"""Cover platform for EnOcean / OPUS jalousie actuators (RPS-controlled)."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.cover import (
    PLATFORM_SCHEMA,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_RECEIVER_ID,
    CONF_SENDER_ID,
    COVER_DOWN,
    COVER_UP,
    DATA_DONGLE,
    DOMAIN,
    OPUS_RELEASE,
    PRESS_RELEASE_DELAY,
    STATUS_PRESSED,
    STATUS_RELEASED,
)
from .device import EnOceanDevice
from .dongle import format_id
from .helpers import ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Cover"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENDER_ID): ENOCEAN_ID,
        vol.Optional(CONF_RECEIVER_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
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
        _LOGGER.warning(
            "Cover '%s' sender_id %s is outside the dongle's valid range "
            "(base_id .. base_id+127). The dongle will refuse to send.",
            name,
            format_id(sender_id),
        )

    async_add_entities([EnOceanCover(hass, sender_id, receiver_id, name)])


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
    ) -> None:
        EnOceanDevice.__init__(self, hass, sender_id, name)
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
        self.dongle.send_rps_command(
            self._sender_id, button_value, status=STATUS_PRESSED
        )
        time.sleep(PRESS_RELEASE_DELAY)
        self.dongle.send_rps_command(
            self._sender_id, OPUS_RELEASE, status=STATUS_RELEASED
        )

    def open_cover(self, **kwargs) -> None:
        _LOGGER.debug(
            "Cover %s -> OPEN (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(COVER_UP)
        self._last_direction = COVER_UP
        self._attr_is_closed = False
        self._attr_is_opening = True
        self._attr_is_closing = False
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs) -> None:
        _LOGGER.debug(
            "Cover %s -> CLOSE (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        self._send_press_release(COVER_DOWN)
        self._last_direction = COVER_DOWN
        self._attr_is_closed = True
        self._attr_is_opening = False
        self._attr_is_closing = True
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs) -> None:
        """Stop the cover by sending another short pulse on the same channel."""
        _LOGGER.debug(
            "Cover %s -> STOP (sender_id=%s)", self._attr_name, self.dev_id_str
        )
        # Send a brief press in the direction we last moved to act as a stop.
        button = self._last_direction if self._last_direction is not None else COVER_UP
        self._send_press_release(button)
        self._attr_is_opening = False
        self._attr_is_closing = False
        self.schedule_update_ha_state()
