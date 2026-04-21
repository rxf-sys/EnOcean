"""Constants for the EnOcean (New) integration."""

DOMAIN = "enocean_new"

DATA_DONGLE = "dongle"

# Configuration keys
CONF_DEVICE_PATH = "device"
CONF_SENDER_ID = "sender_id"
CONF_RECEIVER_ID = "receiver_id"
CONF_CHANNEL = "channel"

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

# RPS button values for OPUS aktoren
OPUS_ON = 0x50
OPUS_OFF = 0x70
OPUS_RELEASE = 0x00

# RPS rocker button values (EEP F6-02-01 / F6-02-02)
RPS_ROCKER_A_ON = 0x10   # AI pressed (rocker A bottom)
RPS_ROCKER_A_OFF = 0x30  # A0 pressed (rocker A top)
RPS_ROCKER_B_ON = 0x50   # BI pressed (rocker B bottom)
RPS_ROCKER_B_OFF = 0x70  # B0 pressed (rocker B top)

# Channel → (ON value, OFF value) mapping.
# USB300 dongles that always send with base_id can use different
# rocker channels to address up to 2 independent devices.
CHANNEL_ON_OFF = {
    0: (RPS_ROCKER_B_ON, RPS_ROCKER_B_OFF),  # Rocker B (default)
    1: (RPS_ROCKER_A_ON, RPS_ROCKER_A_OFF),  # Rocker A
}

# Cover (jalousie) RPS values
COVER_UP = 0x50    # Channel 0 pressed
COVER_DOWN = 0x30  # Channel 1 pressed

# RPS status bytes
STATUS_PRESSED = 0x30   # T21=1, NU=1
STATUS_RELEASED = 0x20  # T21=1, NU=0

# Event sent on the HA bus when a button is pressed
EVENT_BUTTON_PRESSED = "enocean_new.button_pressed"

# Delay (seconds) between press and release telegrams
PRESS_RELEASE_DELAY = 0.05
