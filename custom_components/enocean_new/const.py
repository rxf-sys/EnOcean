"""Constants for the EnOcean (New) integration."""

DOMAIN = "enocean_new"

DATA_DONGLE = "dongle"

# Configuration keys
CONF_DEVICE_PATH = "device"
CONF_SENDER_ID = "sender_id"
CONF_RECEIVER_ID = "receiver_id"
CONF_CHANNEL = "channel"
CONF_ON_DATA = "on_data"
CONF_OFF_DATA = "off_data"
CONF_UP_DATA = "up_data"
CONF_DOWN_DATA = "down_data"

# Default values
DEFAULT_NAME = "EnOcean device"
DEFAULT_BAUDRATE = 57600

# ESP3 packet types
PACKET_RADIO_ERP1 = 0x01
PACKET_RESPONSE = 0x02
PACKET_RADIO_SUB_TEL = 0x03
PACKET_EVENT = 0x04
PACKET_COMMON_COMMAND = 0x05
PACKET_SMART_ACK_COMMAND = 0x06
PACKET_REMOTE_MAN_COMMAND = 0x07
PACKET_RADIO_MESSAGE = 0x09
PACKET_RADIO_ERP2 = 0x0A

# ESP3 sync byte
ESP3_SYNC_BYTE = 0x55

# Common Commands (CO_*)
CO_WR_IDBASE = 0x07
CO_RD_IDBASE = 0x08
CO_RD_VERSION = 0x03

# RORG (Radio choice byte)
RORG_RPS = 0xF6  # Repeated Switch (rocker)
RORG_1BS = 0xD5  # 1 Byte Sensor
RORG_4BS = 0xA5  # 4 Byte Sensor
RORG_VLD = 0xD2  # Variable Length Data

# ESP3 return codes (first data byte of a RESPONSE packet)
RET_OK = 0x00
RETURN_CODE_NAMES = {
    0x00: "RET_OK",
    0x01: "RET_ERROR",
    0x02: "RET_NOT_SUPPORTED",
    0x03: "RET_WRONG_PARAM",
    0x04: "RET_OPERATION_DENIED",
    0x05: "RET_LOCK_SET",
    0x06: "RET_BUFFER_TO_SMALL",
    0x07: "RET_NO_FREE_BUFFER",
}

# Valid base ID range (ESP3 CO_RD_IDBASE): 0xFF800000..0xFFFFFF80,
# always aligned to a 128-ID block.
BASE_ID_MIN = 0xFF800000
BASE_ID_MAX = 0xFFFFFF80
BASE_ID_BLOCK = 128

# Seconds to wait for the dongle's RESPONSE. ESP3 specifies 500 ms for
# radio telegrams; the startup commands get more slack.
RESPONSE_TIMEOUT = 0.5
STARTUP_RESPONSE_TIMEOUT = 2.0

# RPS data byte for "button released"
OPUS_RELEASE = 0x00

# RPS rocker button values (EEP F6-02-01 / F6-02-02)
RPS_ROCKER_A_ON = 0x10   # AI pressed (rocker A bottom)
RPS_ROCKER_A_OFF = 0x30  # A0 pressed (rocker A top)
RPS_ROCKER_B_ON = 0x50   # BI pressed (rocker B bottom)
RPS_ROCKER_B_OFF = 0x70  # B0 pressed (rocker B top)

# Channel → default (ON value, OFF value) mapping. Override per entity with
# on_data / off_data if an actuator interprets the rocker the other way round.
CHANNEL_ON_OFF = {
    0: (RPS_ROCKER_B_ON, RPS_ROCKER_B_OFF),  # Rocker B (default)
    1: (RPS_ROCKER_A_ON, RPS_ROCKER_A_OFF),  # Rocker A
}

# Cover (jalousie) default RPS values: both directions on rocker B
COVER_UP = RPS_ROCKER_B_OFF    # B0 pressed (rocker B top)
COVER_DOWN = RPS_ROCKER_B_ON   # BI pressed (rocker B bottom)

# RPS status bytes
STATUS_PRESSED = 0x30   # T21=1, NU=1
STATUS_RELEASED = 0x20  # T21=1, NU=0

# Event sent on the HA bus when a button is pressed
EVENT_BUTTON_PRESSED = "enocean_new.button_pressed"

# Delay (seconds) between press and release telegrams
PRESS_RELEASE_DELAY = 0.05
