"""EnOcean USB300 dongle driver with a minimal ESP3 implementation.

This module deliberately does NOT use the upstream ``enocean`` Python library.
It talks ESP3 directly so that every outgoing RPS telegram carries exactly the
configured sender ID (chip ID or base_id + 0..127) and so that the dongle's
RESPONSE to every command is checked.

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
import time
from typing import Callable, List, Optional

import serial

from .const import (
    BASE_ID_BLOCK,
    BASE_ID_MAX,
    BASE_ID_MIN,
    CO_RD_IDBASE,
    CO_RD_VERSION,
    DEFAULT_BAUDRATE,
    ESP3_SYNC_BYTE,
    OPUS_RELEASE,
    PACKET_COMMON_COMMAND,
    PACKET_RADIO_ERP1,
    PACKET_RESPONSE,
    PRESS_RELEASE_DELAY,
    RESPONSE_TIMEOUT,
    RET_OK,
    RETURN_CODE_NAMES,
    RORG_1BS,
    RORG_4BS,
    RORG_RPS,
    RORG_VLD,
    STARTUP_RESPONSE_TIMEOUT,
    STATUS_PRESSED,
    STATUS_RELEASED,
)

_LOGGER = logging.getLogger(__name__)


class DongleError(Exception):
    """The dongle is not connected, did not answer or rejected a command."""


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


def telegram_event_data(packet: dict) -> dict:
    """Return a received radio packet as plain, JSON-friendly event data."""
    return {
        "sender_id": format_id(packet["sender_id"]),
        "rorg": f"0x{packet['rorg']:02X}",
        "data": " ".join(f"0x{b:02X}" for b in packet.get("data", [])),
        "status": f"0x{packet.get('status', 0):02X}",
        "dbm": packet.get("dbm"),
    }


def is_plausible_base_id(base_id) -> bool:
    """Return True if base_id is a valid ESP3 base ID (0xFF800000..0xFFFFFF80, 128-aligned)."""
    if base_id is None or len(base_id) != 4:
        return False
    value = int.from_bytes(bytes(base_id), "big")
    return BASE_ID_MIN <= value <= BASE_ID_MAX and value % BASE_ID_BLOCK == 0


class EnOceanDongle:
    """Minimal driver for the EnOcean USB300 dongle (ESP3 over serial)."""

    def __init__(self, hass, port: str) -> None:
        self.hass = hass
        self.port = port
        self._serial: Optional[serial.Serial] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._reader_error: Optional[str] = None
        self._listeners: List[Callable[[dict], None]] = []
        # Serialises request/response pairs so a RESPONSE is never matched
        # to the wrong command.
        self._transact_lock = threading.Lock()
        # Keeps press + release telegrams of one button action together.
        self._sequence_lock = threading.Lock()
        self._response_event = threading.Event()
        self._last_response: Optional[dict] = None
        self.base_id: Optional[List[int]] = None
        self.chip_id: Optional[List[int]] = None

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #
    @property
    def connected(self) -> bool:
        """Return True while the port is open and the reader thread runs."""
        return (
            self._serial is not None
            and self._thread is not None
            and self._thread.is_alive()
        )

    def connect(self) -> None:
        """Open the serial port, start the read loop and identify the dongle.

        Raises DongleError if the dongle does not answer or reports an
        implausible base ID; the port is closed again in that case.
        """
        _LOGGER.info("Opening EnOcean dongle on %s", self.port)
        self._serial = serial.Serial(
            self.port,
            baudrate=DEFAULT_BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.1,
            exclusive=True,
        )
        self._serial.reset_input_buffer()
        self._reader_error = None
        self._running = True
        self._thread = threading.Thread(
            target=self._read_loop, name="enocean_new_reader", daemon=True
        )
        self._thread.start()

        try:
            self.base_id = self._read_base_id()
        except DongleError as err:
            self.disconnect()
            raise DongleError(
                f"EnOcean dongle on {self.port} did not report its base ID: "
                f"{err}. Make sure no other add-on or integration (e.g. an "
                "EnOcean MQTT bridge or the core enocean integration) uses "
                "the same stick."
            ) from err

        base_int = int.from_bytes(bytes(self.base_id), "big")
        _LOGGER.info(
            "EnOcean dongle base_id: %s  Valid sender range: %s .. %s "
            "(128 addresses)",
            format_id(self.base_id),
            format_id(self.base_id),
            format_id((base_int + BASE_ID_BLOCK - 1).to_bytes(4, "big")),
        )

        try:
            version = self._read_version()
        except DongleError as err:
            _LOGGER.warning("Could not read dongle firmware version: %s", err)
            return
        self.chip_id = version["chip_id"]
        _LOGGER.info(
            "EnOcean dongle firmware: app=%s api=%s chip=%s description='%s'",
            version["app_version"],
            version["api_version"],
            format_id(self.chip_id),
            version["app_description"],
        )

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
            except serial.SerialException as err:
                _LOGGER.debug("Error while closing serial port: %s", err)
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
    # Sender-ID validation
    # ------------------------------------------------------------------ #
    def is_valid_sender(self, sender_id) -> bool:
        """Return True if the dongle may transmit with sender_id.

        A TCM310/USB300 only transmits with its chip ID or with one of the
        128 IDs starting at its base ID. The 4-byte IDs are compared as
        32-bit integers so byte boundary crossings are handled correctly.
        """
        if sender_id is None or len(sender_id) != 4:
            return False
        sid = [int(b) & 0xFF for b in sender_id]
        if self.chip_id is not None and sid == self.chip_id:
            return True
        return self._sender_offset(sid) is not None

    def _sender_offset(self, sender_id) -> Optional[int]:
        """Calculate the offset of sender_id from base_id."""
        if not self.base_id or sender_id is None or len(sender_id) != 4:
            return None
        base = int.from_bytes(bytes(self.base_id), "big")
        sid = int.from_bytes(bytes(sender_id), "big")
        diff = sid - base
        return diff if 0 <= diff < BASE_ID_BLOCK else None

    def sender_range_str(self) -> str:
        """Return a human readable description of the valid sender IDs."""
        if not self.base_id:
            return "unknown (base ID not read)"
        base = int.from_bytes(bytes(self.base_id), "big")
        text = (
            f"{format_id(self.base_id)} .. "
            f"{format_id((base + BASE_ID_BLOCK - 1).to_bytes(4, 'big'))}"
        )
        if self.chip_id:
            text += f" or chip ID {format_id(self.chip_id)}"
        return text

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

    def transact(
        self,
        packet_type: int,
        data: bytes,
        optional_data: bytes = b"",
        timeout: float = RESPONSE_TIMEOUT,
    ) -> bytes:
        """Send one ESP3 frame and wait for the dongle's RESPONSE.

        Returns the RESPONSE data (starting with the return code). Raises
        DongleError if the dongle is not connected, does not answer within
        ``timeout`` seconds or returns a code other than RET_OK.
        """
        if not self.connected:
            reason = f" ({self._reader_error})" if self._reader_error else ""
            raise DongleError(
                f"EnOcean dongle on {self.port} is not connected{reason}"
            )
        packet = self.build_packet(packet_type, data, optional_data)
        with self._transact_lock:
            self._response_event.clear()
            self._last_response = None
            _LOGGER.debug("TX %s", packet.hex())
            try:
                self._serial.write(packet)
                self._serial.flush()
            except serial.SerialException as err:
                raise DongleError(f"Serial write failed: {err}") from err
            if not self._response_event.wait(timeout):
                raise DongleError(
                    f"No RESPONSE from dongle within {timeout:.1f} s"
                    + (f" ({self._reader_error})" if self._reader_error else "")
                )
            response = self._last_response

        resp_data = response["data"] if response else b""
        if not resp_data:
            raise DongleError("Empty RESPONSE from dongle")
        return_code = resp_data[0]
        if return_code != RET_OK:
            raise DongleError(
                "Dongle rejected the command: "
                + RETURN_CODE_NAMES.get(return_code, f"0x{return_code:02X}")
            )
        return resp_data

    def send_rps_command(
        self,
        sender_id,
        data_byte: int,
        status: int = STATUS_PRESSED,
        destination: Optional[List[int]] = None,
    ) -> None:
        """Send one RPS (F6) telegram with the EXACT sender_id provided.

        Raises DongleError if sender_id is not allowed for this dongle or the
        dongle does not acknowledge the telegram.
        """
        if sender_id is None or len(sender_id) != 4:
            raise ValueError("sender_id must be a 4-byte sequence")

        sid = [int(b) & 0xFF for b in sender_id]
        if not self.is_valid_sender(sid):
            raise DongleError(
                f"Sender ID {format_id(sid)} is not allowed for this dongle. "
                f"Valid: {self.sender_range_str()}"
            )

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
        dest = (
            [int(b) & 0xFF for b in destination]
            if destination
            else [0xFF, 0xFF, 0xFF, 0xFF]
        )
        optional = bytes([0x03, dest[0], dest[1], dest[2], dest[3], 0xFF, 0x00])

        offset = self._sender_offset(sid)
        _LOGGER.info(
            "TX RPS sender=%s (%s) data=0x%02X status=0x%02X dest=%s",
            format_id(sid),
            f"base+{offset}" if offset is not None else "chip ID",
            data_byte,
            status,
            format_id(dest),
        )
        self.transact(PACKET_RADIO_ERP1, data, optional)

    def send_rps_press_release(
        self, sender_id, data_byte: int, status: int = STATUS_PRESSED
    ) -> None:
        """Send a rocker press followed by the release telegram.

        The release is only sent after the dongle acknowledged the press.
        Both telegrams are kept together even if several actions run
        concurrently.
        """
        with self._sequence_lock:
            self.send_rps_command(sender_id, data_byte, status=status)
            time.sleep(PRESS_RELEASE_DELAY)
            self.send_rps_command(
                sender_id, OPUS_RELEASE, status=STATUS_RELEASED
            )

    # ------------------------------------------------------------------ #
    # Common commands
    # ------------------------------------------------------------------ #
    def _read_base_id(self) -> List[int]:
        """Read and validate the dongle's base ID via CO_RD_IDBASE."""
        data = self.transact(
            PACKET_COMMON_COMMAND,
            bytes([CO_RD_IDBASE]),
            timeout=STARTUP_RESPONSE_TIMEOUT,
        )
        # Response: return_code (1) + base_id (4)
        if len(data) < 5:
            raise DongleError(f"Unexpected base ID response: {data.hex()}")
        base_id = list(data[1:5])
        if not is_plausible_base_id(base_id):
            raise DongleError(
                f"Implausible base ID {format_id(base_id)} "
                "(expected FF:80:00:00 .. FF:FF:FF:80, 128-aligned)"
            )
        return base_id

    def _read_version(self) -> dict:
        """Read the dongle firmware version via CO_RD_VERSION."""
        data = self.transact(
            PACKET_COMMON_COMMAND,
            bytes([CO_RD_VERSION]),
            timeout=STARTUP_RESPONSE_TIMEOUT,
        )
        # Response: return_code(1) + APP_VERSION(4) + API_VERSION(4)
        #           + CHIP_ID(4) + CHIP_VERSION(4) + APP_DESCRIPTION(16)
        if len(data) < 17:
            raise DongleError(f"Unexpected version response: {data.hex()}")
        return {
            "app_version": ".".join(str(b) for b in data[1:5]),
            "api_version": ".".join(str(b) for b in data[5:9]),
            "chip_id": list(data[9:13]),
            "chip_version": ".".join(str(b) for b in data[13:17]),
            "app_description": (
                data[17:33].decode("ascii", errors="replace").rstrip("\x00")
                if len(data) >= 33
                else "unknown"
            ),
        }

    # ------------------------------------------------------------------ #
    # Read loop
    # ------------------------------------------------------------------ #
    def _read_loop(self) -> None:
        buf = bytearray()
        while self._running:
            try:
                chunk = self._serial.read(64)
            except serial.SerialException as err:
                self._reader_error = f"serial read failed: {err}"
                _LOGGER.error(
                    "Serial read failed, stopping reader: %s. Is another "
                    "add-on or integration using the same stick?",
                    err,
                )
                break
            except Exception as err:  # noqa: BLE001
                self._reader_error = f"unexpected reader error: {err}"
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
        if packet_type == PACKET_RESPONSE:
            rc = data[0] if data else -1
            _LOGGER.debug("RX RESPONSE return_code=%d data=%s", rc, data.hex())
            self._last_response = {"data": data, "opt": opt_data}
            self._response_event.set()
            return

        if packet_type == PACKET_RADIO_ERP1:
            packet_info = self._parse_radio(data, opt_data)
            if packet_info:
                # Optional data of a received ERP1: subtel, destination (4),
                # dBm (positive value of the negative RSSI), security level.
                if len(opt_data) >= 6:
                    packet_info["dbm"] = -opt_data[5]
                _LOGGER.info(
                    "RX RADIO rorg=0x%02X sender=%s data=%s status=0x%02X",
                    packet_info["rorg"],
                    format_id(packet_info["sender_id"]),
                    " ".join(f"0x{b:02X}" for b in packet_info.get("data", [])),
                    packet_info.get("status", 0),
                )
            else:
                _LOGGER.debug(
                    "RX RADIO (unparsed) data=%s opt=%s", data.hex(), opt_data.hex()
                )
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
