"""Switch platform for OPUS / EnOcean classic actuators (RPS-controlled).

``channel`` (0 = rocker B, 1 = rocker A) selects the default ON/OFF data
bytes; ``on_data`` / ``off_data`` override them for actuators that interpret
the rocker the other way round.

``wall_switches`` lists physical rocker switches that are taught to the same
actuator. Their presses update the (otherwise assumed) entity state, so Home
Assistant follows when the light is switched at the wall.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, PlatformNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from .const import (
    CONF_ACTUATOR,
    CHANNEL_ON_OFF,
    CONF_CHANNEL,
    CONF_OFF_DATA,
    CONF_ON_DATA,
    CONF_RECEIVER_ID,
    CONF_SENDER_ID,
    CONF_WALL_SWITCHES,
    DATA_DONGLE,
    DOMAIN,
    RORG_1BS,
    RORG_RPS,
    WALL_SWITCH_DEDUP_WINDOW,
)
from .device import (
    EnOceanDevice,
    device_row,
    register_device,
    unregister_device,
)
from .dongle import DongleError, format_id
from .helpers import DATA_BYTE, ENOCEAN_ID

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "EnOcean Switch"

# A wall switch: its ID and the data bytes of the keys that switch the
# actuator on and off. Equal on_data and off_data mean a universal pushbutton
# that toggles on every press.
WALL_SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required("id"): ENOCEAN_ID,
        vol.Required(CONF_ON_DATA): DATA_BYTE,
        vol.Required(CONF_OFF_DATA): DATA_BYTE,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SENDER_ID): ENOCEAN_ID,
        vol.Optional(CONF_RECEIVER_ID): ENOCEAN_ID,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
        vol.Optional(CONF_ACTUATOR): cv.string,
        vol.Optional(CONF_CHANNEL, default=0): vol.In([0, 1]),
        vol.Optional(CONF_ON_DATA): DATA_BYTE,
        vol.Optional(CONF_OFF_DATA): DATA_BYTE,
        vol.Optional(CONF_WALL_SWITCHES, default=[]): vol.All(
            cv.ensure_list, [WALL_SWITCH_SCHEMA]
        ),
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
        # The dongle may still be starting (or retrying after the USB stick
        # appeared late); Home Assistant retries the platform setup.
        raise PlatformNotReady("EnOcean dongle is not initialised yet")

    sender_id: List[int] = config[CONF_SENDER_ID]
    receiver_id: Optional[List[int]] = config.get(CONF_RECEIVER_ID)
    name: str = config[CONF_NAME]
    channel: int = config[CONF_CHANNEL]
    default_on, default_off = CHANNEL_ON_OFF[channel]
    on_value: int = config.get(CONF_ON_DATA, default_on)
    off_value: int = config.get(CONF_OFF_DATA, default_off)

    dongle = hass.data[DOMAIN][DATA_DONGLE]
    if not dongle.is_valid_sender(sender_id):
        _LOGGER.error(
            "Switch '%s' not created: sender_id %s is not allowed for this "
            "dongle. Valid: %s",
            name,
            format_id(sender_id),
            dongle.sender_range_str(),
        )
        return

    async_add_entities(
        [
            EnOceanSwitch(
                hass,
                sender_id,
                receiver_id,
                name,
                channel,
                on_value,
                off_value,
                config[CONF_WALL_SWITCHES],
                config.get(CONF_ACTUATOR),
            )
        ]
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
        channel: int,
        on_value: int,
        off_value: int,
        wall_switches: Optional[List[dict]] = None,
        actuator: Optional[str] = None,
    ) -> None:
        EnOceanDevice.__init__(self, hass, sender_id, name)
        self._sender_id: List[int] = [int(b) & 0xFF for b in sender_id]
        self._receiver_id: Optional[List[int]] = (
            [int(b) & 0xFF for b in receiver_id] if receiver_id else None
        )
        self._attr_name = name
        self._attr_is_on = False
        # Classic RPS actuators (e.g. OPUS greenNet REG) send no status, so
        # the state is always optimistic. receiver_id feedback, if any,
        # merely corrects it.
        self._attr_assumed_state = True

        self._on_value = on_value
        self._off_value = off_value
        self._channel = channel
        self._wall_switches = [
            {
                "id": [int(b) & 0xFF for b in ws["id"]],
                "on": ws[CONF_ON_DATA],
                "off": ws[CONF_OFF_DATA],
            }
            for ws in (wall_switches or [])
        ]
        self._last_wall_press: Optional[tuple] = None
        self._actuator = actuator

        self._attr_unique_id = (
            "enocean_new_switch_"
            + "".join(f"{b:02x}" for b in self._sender_id)
            + f"_ch{channel}"
        )

    @property
    def _listens(self) -> bool:
        return self._receiver_id is not None or bool(self._wall_switches)

    async def async_added_to_hass(self) -> None:
        """Register packet listener once entity is fully added."""
        name = self._attr_name
        rows = [
            device_row(
                self._sender_id,
                "Schalter",
                "HA sendet",
                f"HA → {name}",
                f"an 0x{self._on_value:02X} / aus 0x{self._off_value:02X}",
            )
        ]
        rows += [
            device_row(
                ws["id"],
                "Wandschalter",
                "empfängt",
                f"Wandschalter → {name}",
                f"an 0x{ws['on']:02X} / aus 0x{ws['off']:02X}",
            )
            for ws in self._wall_switches
        ]
        if self._receiver_id is not None:
            rows.append(
                device_row(
                    self._receiver_id, "Rückmeldung", "empfängt", f"Aktor → {name}"
                )
            )
        register_device(self.hass, self.entity_id, name, self._actuator, rows)
        if self._listens:
            self.dongle.add_listener(self._packet_received)

    async def async_will_remove_from_hass(self) -> None:
        unregister_device(self.hass, self.entity_id)
        if self._listens:
            self.dongle.remove_listener(self._packet_received)

    # ------------------------------------------------------------------ #
    # RX
    # ------------------------------------------------------------------ #
    def _packet_received(self, packet: dict) -> None:
        """Handle wall switch presses and status feedback from the actor."""
        sender = packet.get("sender_id")
        for wall_switch in self._wall_switches:
            if sender == wall_switch["id"]:
                self._wall_switch_pressed(wall_switch, packet)
                return

        if not self._receiver_id or sender != self._receiver_id:
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

    def _wall_switch_pressed(self, wall_switch: dict, packet: dict) -> None:
        """Mirror a wall switch press into the entity state."""
        data = packet.get("data") or []
        status = packet.get("status", 0)
        # Only rocker presses (NU bit set, data != 0); releases carry 0x00.
        if packet.get("rorg") != RORG_RPS or not data or not status & 0x10:
            return
        value = data[0]
        if value not in (wall_switch["on"], wall_switch["off"]):
            return

        # The same press can arrive twice (direct and via a repeater).
        now = time.monotonic()
        key = (tuple(wall_switch["id"]), value)
        last = self._last_wall_press
        self._last_wall_press = (key, now)
        if last and last[0] == key and now - last[1] < WALL_SWITCH_DEDUP_WINDOW:
            return

        if wall_switch["on"] == wall_switch["off"]:
            self._update_state(not self._attr_is_on)
        else:
            self._update_state(value == wall_switch["on"])

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
        try:
            self.dongle.send_rps_press_release(self._sender_id, button_value)
        except DongleError as err:
            raise HomeAssistantError(
                f"{self._attr_name}: sending failed: {err}"
            ) from err

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
