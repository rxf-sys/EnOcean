"""Tests for the ESP3 dongle driver (stdlib only, serial port simulated).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import importlib
import pathlib
import queue
import sys
import types
import unittest

COMPONENT_DIR = (
    pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "enocean_new"
)


class FakeSerialException(Exception):
    """Stand-in for serial.SerialException."""


def _load_dongle_module():
    """Import dongle.py without importing Home Assistant or pyserial."""
    serial_stub = types.ModuleType("serial")
    serial_stub.SerialException = FakeSerialException
    serial_stub.EIGHTBITS = 8
    serial_stub.PARITY_NONE = "N"
    serial_stub.STOPBITS_ONE = 1
    serial_stub.Serial = None  # replaced per test
    sys.modules["serial"] = serial_stub

    package = types.ModuleType("enocean_new_under_test")
    package.__path__ = [str(COMPONENT_DIR)]
    sys.modules["enocean_new_under_test"] = package
    return importlib.import_module("enocean_new_under_test.dongle")


dongle_mod = _load_dongle_module()
EnOceanDongle = dongle_mod.EnOceanDongle
DongleError = dongle_mod.DongleError

BASE_ID = bytes([0xFF, 0xC8, 0x31, 0x80])
CHIP_ID = bytes([0x05, 0xA7, 0x90, 0x63])


def frame(packet_type: int, data: bytes) -> bytes:
    return EnOceanDongle.build_packet(packet_type, data)


def version_response(chip_id: bytes = CHIP_ID) -> bytes:
    desc = b"GATEWAYCTRL".ljust(16, b"\x00")
    data = bytes([0]) + bytes([2, 11, 1, 0]) + bytes([2, 6, 3, 0]) + chip_id
    return frame(0x02, data + bytes([0x45, 0x4F, 0x03, 0x01]) + desc)


class FakeSerial:
    """Simulated USB300: answers each written frame from a script."""

    def __init__(self, answers):
        # answers: callable(written_frame) -> bytes to deliver (or b"")
        self._answers = answers
        self._rx: "queue.Queue[bytes]" = queue.Queue()
        self.written: list[bytes] = []
        self.read_error: Exception | None = None
        self.closed = False

    def read(self, _size):
        if self.read_error is not None:
            raise self.read_error
        try:
            return self._rx.get(timeout=0.01)
        except queue.Empty:
            return b""

    def write(self, data):
        self.written.append(bytes(data))
        answer = self._answers(bytes(data))
        if answer:
            self._rx.put(answer)

    def flush(self):
        pass

    def reset_input_buffer(self):
        pass

    def close(self):
        self.closed = True


def make_answers(base_id=BASE_ID, radio_rc=0, respond=True):
    def answers(written: bytes) -> bytes:
        if not respond:
            return b""
        packet_type, payload = written[4], written[6]
        if packet_type == 0x05 and payload == 0x08:  # CO_RD_IDBASE
            return frame(0x02, bytes([0]) + base_id)
        if packet_type == 0x05 and payload == 0x03:  # CO_RD_VERSION
            return version_response()
        if packet_type == 0x01:  # RADIO_ERP1
            return frame(0x02, bytes([radio_rc]))
        return frame(0x02, bytes([0x02]))  # RET_NOT_SUPPORTED

    return answers


class DongleTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_startup = dongle_mod.STARTUP_RESPONSE_TIMEOUT
        self._orig_delay = dongle_mod.PRESS_RELEASE_DELAY
        dongle_mod.STARTUP_RESPONSE_TIMEOUT = 0.3
        dongle_mod.PRESS_RELEASE_DELAY = 0
        self.dongle = None

    def tearDown(self):
        if self.dongle is not None:
            self.dongle.disconnect()
        dongle_mod.STARTUP_RESPONSE_TIMEOUT = self._orig_startup
        dongle_mod.PRESS_RELEASE_DELAY = self._orig_delay

    def connect(self, answers):
        self.fake = FakeSerial(answers)
        dongle_mod.serial.Serial = lambda *args, **kwargs: self.fake
        self.dongle = EnOceanDongle(hass=None, port="/dev/fake")
        self.dongle.connect()
        return self.dongle

    def radio_frames(self):
        return [f for f in self.fake.written if f[4] == 0x01]


class ConnectTests(DongleTestCase):
    def test_reads_base_id_and_chip_id(self):
        dongle = self.connect(make_answers())
        self.assertEqual(dongle.base_id, list(BASE_ID))
        self.assertEqual(dongle.chip_id, list(CHIP_ID))
        self.assertTrue(dongle.connected)

    def test_reference_frame_for_base_id_request(self):
        self.connect(make_answers())
        self.assertEqual(self.fake.written[0].hex(), "5500010005700838")

    def test_implausible_base_id_fails_and_closes_port(self):
        with self.assertRaisesRegex(DongleError, "Implausible base ID"):
            self.connect(make_answers(base_id=CHIP_ID))
        self.assertTrue(self.fake.closed)
        self.assertFalse(self.dongle.connected)

    def test_no_response_fails_with_port_sharing_hint(self):
        with self.assertRaisesRegex(DongleError, "same stick"):
            self.connect(make_answers(respond=False))

    def test_reader_failure_is_reported(self):
        fake = FakeSerial(make_answers())
        fake.read_error = FakeSerialException(
            "device reports readiness to read but returned no data"
        )
        dongle_mod.serial.Serial = lambda *args, **kwargs: fake
        self.fake = fake
        self.dongle = EnOceanDongle(hass=None, port="/dev/fake")
        with self.assertRaisesRegex(DongleError, "returned no data"):
            self.dongle.connect()


class SenderValidationTests(DongleTestCase):
    def setUp(self):
        super().setUp()
        self.connect(make_answers())

    def test_base_range_and_chip_id_are_valid(self):
        self.assertTrue(self.dongle.is_valid_sender([0xFF, 0xC8, 0x31, 0x80]))
        self.assertTrue(self.dongle.is_valid_sender([0xFF, 0xC8, 0x31, 0xFF]))
        self.assertTrue(self.dongle.is_valid_sender(list(CHIP_ID)))

    def test_outside_range_is_invalid(self):
        self.assertFalse(self.dongle.is_valid_sender([0xFF, 0xC8, 0x32, 0x00]))
        self.assertFalse(self.dongle.is_valid_sender([0x05, 0xA7, 0x90, 0x64]))
        self.assertFalse(self.dongle.is_valid_sender([0xFF, 0xC8, 0x31]))

    def test_invalid_sender_is_not_transmitted(self):
        with self.assertRaisesRegex(DongleError, "not allowed"):
            self.dongle.send_rps_command([0x05, 0xA7, 0x90, 0x64], 0x50)
        self.assertEqual(self.radio_frames(), [])


class SendTests(DongleTestCase):
    def test_press_release_sends_two_acknowledged_telegrams(self):
        self.connect(make_answers())
        self.dongle.send_rps_press_release([0xFF, 0xC8, 0x31, 0x81], 0x70)
        press, release = self.radio_frames()
        # data: F6, data_byte, sender(4), status
        self.assertEqual(press[6:13].hex(), "f670ffc8318130")
        self.assertEqual(release[6:13].hex(), "f600ffc8318120")
        # optional: subtel 3, broadcast destination, dBm FF, security 0
        self.assertEqual(press[13:20].hex(), "03ffffffffff00")

    def test_rejected_telegram_raises_and_skips_release(self):
        self.connect(make_answers(radio_rc=0x03))
        with self.assertRaisesRegex(DongleError, "RET_WRONG_PARAM"):
            self.dongle.send_rps_press_release([0xFF, 0xC8, 0x31, 0x81], 0x70)
        self.assertEqual(len(self.radio_frames()), 1)

    def test_send_after_reader_stopped_fails_fast(self):
        self.connect(make_answers())
        self.fake.read_error = FakeSerialException("device disconnected")
        self.dongle._thread.join(timeout=1)
        with self.assertRaisesRegex(DongleError, "not connected.*disconnected"):
            self.dongle.send_rps_command([0xFF, 0xC8, 0x31, 0x81], 0x70)


if __name__ == "__main__":
    unittest.main()
