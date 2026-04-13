"""EnOcean USB300 dongle driver with a minimal ESP3 implementation.

This module deliberately does NOT use the upstream ``enocean`` Python library
because that library overwrites the sender address of every outgoing radio
telegram with the dongle's base ID. For OPUS classic devices we MUST be able
to send distinct sender IDs (base_id + offset 1..127) so that each actor can
be teached in to a unique virtual rocker switch.

The ESP3 frame format implemented here is:

    SYNC (1 byte = 0x55)
    Header (4 bytes):  data_len_h, data_len_l, opt_len, packet_type
    CRC8 of header (1 byte)
    Data (data_len bytes)
    Optional Data (opt_len bytes)
    CRC8 of (data + optional_data) (1 byte)
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, List, Optional

import serial

from .const import (
    CO_RD_IDBASE,
    DEFAULT_BAUDRATE,
    ESP3_SYNC_BYTE,
    PACKET_COMMON_COMMAND,
    PACKET_RADIO_ERP1,
    PACKET_RESPONSE,
    RORG_1BS,
    RORG_4BS,
    RORG_RPS,
    RORG_VLD,
)

_LOGGER = logging.getLogger(__name__)


def crc8(data: bytes) -> int:
    """Calculate EnOcean CRC8 (polynomial 0x07, init 0x00)."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc


def format_id(id_bytes) -> str:
    """Format a 4-byte device ID as colon-separated hex."""
    return ":".join(f"{b:02X}" for b in id_bytes)


class EnOceanDongle:
    """Minimal driver for the EnOcean USB300 dongle (ESP3 over serial)."""

    def __init__(self, hass, port: str) -> None:
        self.hass = hass
        self.port = port
        self._serial: Optional[serial.Serial] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._listeners: List[Callable[[dict], None]] = []
        self._write_lock = threading.Lock()
        self._response_event = threading.Event()
        self._last_response: Optional[dict] = None
        self.base_id: Optional[List[int]] = None

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Open the serial port and start the read loop."""
        _LOGGER.info("Opening EnOcean dongle on %s", self.port)
        self._serial = serial.Serial(
            self.port,
            baudrate=DEFAULT_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
        )
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, name="enocean_new_reader", daemon=True
        )
        self._thread.start()

        # Try to read base ID. Best effort - if it fails the dongle will still
        # accept telegrams that we send.
        try:
            self.base_id = self._read_base_id()
            if self.base_id:
                _LOGGER.info(
                    "EnOcean dongle base ID: %s (valid sender range: %s .. %s)",
                    format_id(self.base_id),
                    format_id(self.base_id),
                    format_id(self.base_id[:3] + [(self.base_id[3] + 127) & 0xFF]),
                )
            else:
                _LOGGER.warning("Could not read base ID from dongle")
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error while reading base ID")

    def disconnect(self) -> None:
        """Stop the read loop and close the serial port."""
        _LOGGER.info("Closing EnOcean dongle on %s", self.port)
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001
                pass
            self._serial = None

    # ------------------------------------------------------------------ #
    # Listener handling
    # ------------------------------------------------------------------ #
    def add_listener(self, callback: Callable[[dict], None]) -> None:
        """Register a callback that is fired for every received radio packet."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[dict], None]) -> None:
        """Remove a previously registered listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    # ------------------------------------------------------------------ #
    # Packet construction / send
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_packet(
        packet_type: int, data: bytes, optional_data: bytes = b""
    ) -> bytes:
        """Build a raw ESP3 frame."""
        data_len = len(data)
        opt_len = len(optional_data)
        header = bytes(
            [
                (data_len >> 8) & 0xFF,
                data_len & 0xFF,
                opt_len & 0xFF,
                packet_type & 0xFF,
            ]
        )
        crc_h = crc8(header)
        crc_d = crc8(data + optional_data)
        return (
            bytes([ESP3_SYNC_BYTE])
            + header
            + bytes([crc_h])
            + data
            + optional_data
            + bytes([crc_d])
        )

    def send_packet(
        self, packet_type: int, data: bytes, optional_data: bytes = b""
    ) -> None:
        """Write a raw ESP3 frame to the dongle."""
        if self._serial is None:
            _LOGGER.error("Cannot send packet: serial port not open")
            return
        packet = self.build_packet(packet_type, data, optional_data)
        _LOGGER.debug("TX %s", packet.hex())
        with self._write_lock:
            try:
                self._serial.write(packet)
                self._serial.flush()
            except serial.SerialException as err:
                _LOGGER.error("Serial write failed: %s", err)

    def send_rps_command(
        self,
        sender_id,
        data_byte: int,
        status: int = 0x30,
    ) -> None:
        """Send a RPS (F6) telegram with the EXACT sender_id provided.

        CRITICAL: sender_id is used unchanged. It is NEVER replaced by the
        dongle's base ID. This is the bug that the upstream enocean library
        and its derivatives suffer from.
        """
        if sender_id is None or len(sender_id) != 4:
            raise ValueError("sender_id must be a 4-byte sequence")

        sid = [int(b) & 0xFF for b in sender_id]

        data = bytes(
            [
                RORG_RPS,
                data_byte & 0xFF,
                sid[0],
                sid[1],
                sid[2],
                sid[3],
                status & 0xFF,
            ]
        )
        # Optional data: SubTelNum=3, destination=broadcast, dBm=0xFF, security=0
        optional = bytes([0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

        _LOGGER.debug(
            "Send RPS sender_id=%s data_byte=0x%02X status=0x%02X",
            format_id(sid),
            data_byte,
            status,
        )
        self.send_packet(PACKET_RADIO_ERP1, data, optional)

    def send_1bs_command(self, sender_id, data_byte: int) -> None:
        """Send a 1BS (D5) telegram with the EXACT sender_id provided."""
        if sender_id is None or len(sender_id) != 4:
            raise ValueError("sender_id must be a 4-byte sequence")
        sid = [int(b) & 0xFF for b in sender_id]
        data = bytes(
            [
                RORG_1BS,
                data_byte & 0xFF,
                sid[0],
                sid[1],
                sid[2],
                sid[3],
                0x00,
            ]
        )
        optional = bytes([0x03, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
        _LOGGER.debug(
            "Send 1BS sender_id=%s data_byte=0x%02X",
            format_id(sid),
            data_byte,
        )
        self.send_packet(PACKET_RADIO_ERP1, data, optional)

    # ------------------------------------------------------------------ #
    # Common commands
    # ------------------------------------------------------------------ #
    def _read_base_id(self) -> Optional[List[int]]:
        """Read the dongle's base ID via CO_RD_IDBASE."""
        self._response_event.clear()
        self._last_response = None
        self.send_packet(PACKET_COMMON_COMMAND, bytes([CO_RD_IDBASE]))
        if not self._response_event.wait(timeout=2.0):
            return None
        resp = self._last_response
        if not resp:
            return None
        data = resp.get("data", b"")
        # Response: return_code (1) + base_id (4)
        if len(data) >= 5:
            return list(data[1:5])
        return None

    # ------------------------------------------------------------------ #
    # Read loop
    # ------------------------------------------------------------------ #
    def _read_loop(self) -> None:
        buf = bytearray()
        while self._running:
            try:
                chunk = self._serial.read(64)
            except serial.SerialException as err:
                _LOGGER.error("Serial read failed, stopping reader: %s", err)
                break
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error in read loop")
                break

            if chunk:
                buf.extend(chunk)
                # Try to parse as many complete frames as possible
                while True:
                    consumed = self._try_parse(buf)
                    if consumed == 0:
                        break
                    del buf[:consumed]

    def _try_parse(self, buf: bytearray) -> int:
        """Try to parse one ESP3 frame from buf.

        Returns the number of bytes consumed. Returns 0 if more data is needed.
        """
        if not buf:
            return 0

        # Find sync byte
        sync_idx = buf.find(ESP3_SYNC_BYTE)
        if sync_idx < 0:
            # No sync byte at all - drop the lot
            return len(buf)
        if sync_idx > 0:
            # Drop garbage bytes before sync
            return sync_idx

        # We have a sync byte at position 0. Need at least 6 bytes (sync + header + crc_h)
        if len(buf) < 6:
            return 0

        data_len = (buf[1] << 8) | buf[2]
        opt_len = buf[3]
        packet_type = buf[4]
        crc_h = buf[5]

        if crc8(bytes(buf[1:5])) != crc_h:
            _LOGGER.debug("Header CRC mismatch, skipping sync byte")
            return 1  # skip the sync byte and try again

        total_len = 6 + data_len + opt_len + 1
        if len(buf) < total_len:
            return 0  # need more data

        data = bytes(buf[6 : 6 + data_len])
        opt_data = bytes(buf[6 + data_len : 6 + data_len + opt_len])
        crc_d = buf[total_len - 1]

        if crc8(data + opt_data) != crc_d:
            _LOGGER.debug("Data CRC mismatch, skipping sync byte")
            return 1

        try:
            self._handle_packet(packet_type, data, opt_data)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error while handling received packet")

        return total_len

    def _handle_packet(
        self, packet_type: int, data: bytes, opt_data: bytes
    ) -> None:
        _LOGGER.debug(
            "RX type=0x%02X data=%s opt=%s",
            packet_type,
            data.hex(),
            opt_data.hex(),
        )

        if packet_type == PACKET_RESPONSE:
            self._last_response = {"data": data, "opt": opt_data}
            self._response_event.set()
            return

        if packet_type == PACKET_RADIO_ERP1:
            packet_info = self._parse_radio(data, opt_data)
            if packet_info and self._listeners:
                # Dispatch on the HA event loop so callbacks can safely
                # call schedule_update_ha_state and async_fire.
                try:
                    self.hass.loop.call_soon_threadsafe(
                        self._dispatch_listeners, packet_info
                    )
                except RuntimeError:
                    # Loop closed (shutdown) - ignore
                    pass

    def _dispatch_listeners(self, packet_info: dict) -> None:
        for cb in list(self._listeners):
            try:
                cb(packet_info)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Listener callback raised")

    @staticmethod
    def _parse_radio(data: bytes, opt_data: bytes) -> Optional[dict]:
        if not data:
            return None
        rorg = data[0]

        if rorg == RORG_RPS:
            if len(data) < 7:
                return None
            return {
                "rorg": rorg,
                "data": [data[1]],
                "sender_id": list(data[2:6]),
                "status": data[6],
                "opt": list(opt_data),
            }

        if rorg == RORG_1BS:
            if len(data) < 7:
                return None
            return {
                "rorg": rorg,
                "data": [data[1]],
                "sender_id": list(data[2:6]),
                "status": data[6],
                "opt": list(opt_data),
            }

        if rorg == RORG_4BS:
            if len(data) < 10:
                return None
            return {
                "rorg": rorg,
                "data": list(data[1:5]),
                "sender_id": list(data[5:9]),
                "status": data[9],
                "opt": list(opt_data),
            }

        if rorg == RORG_VLD:
            # Variable length: payload bytes between rorg and (id+status)
            if len(data) < 6:
                return None
            payload = list(data[1:-5])
            return {
                "rorg": rorg,
                "data": payload,
                "sender_id": list(data[-5:-1]),
                "status": data[-1],
                "opt": list(opt_data),
            }

        # Unknown / unsupported
        return None
