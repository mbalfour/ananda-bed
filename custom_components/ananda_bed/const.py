"""Constants for the Ananda Bed integration.

This module defines all protocol constants, motor command bytes, preset bytes,
and vibration level mappings used throughout the integration. These values were
reverse-engineered from packet captures of the official Ananda mobile app
communicating with the Keeson WF02D bed controller over UDP port 5987.

The bed's command protocol uses a 30-byte UDP packet with four "command slots"
(bytes 23-26), each controlling a different class of operation:
    Byte 23: Motor commands (continuous -- motor runs while packets are sent)
    Byte 24: Preset/vibration commands (fire-and-forget or state-cycling)
    Byte 25: Additional commands (memory positions, light toggle)
    Byte 26: Extended commands (flat position)
"""

# Home Assistant integration domain identifier.
# Used as the key in hass.data and for registering the config flow.
DOMAIN = "ananda_bed"

# Config entry data keys
CONF_MAC = "mac_address"
CONF_AUTH_TOKEN = "product_access_key"

# Xlink product access key: a static 16-byte shared secret that authorizes
# local LAN control. This is the same for ALL Ananda beds of this product type
# -- it's hardcoded in both the firmware and the mobile app. It is NOT a
# per-device secret, so it's safe to use as a default.
DEFAULT_AUTH_TOKEN = "4352d88a78aa39750bf70cd6f27bcaa5"  # Xlink product access key (same for all Ananda beds)

# UDP port the bed controller listens on (fixed in firmware)
BED_PORT = 5987

# Rate at which motor commands must be sent to keep motors running.
# The bed expects continuous packets at ~4Hz; motors stop if packets cease.
COMMAND_RATE = 0.25  # 4 Hz

# Maximum encoder tick values when motors are fully raised.
# These are the raw uint16 values from the bed's position sensors.
# Used to convert between bed encoder ticks and HA's 0-100% position scale.
HEAD_MAX = 21138            # Encoder ticks at full head elevation
FEET_MAX = 8924             # Encoder ticks at full feet elevation

# ---------------------------------------------------------------------------
# Motor commands (byte 23 of the command packet)
#
# These are bitmask values, one bit per motor direction. The motor runs
# continuously while command packets containing these bits are sent at 4Hz,
# and stops when packets stop (or a STOP/0x00 is sent).
# ---------------------------------------------------------------------------
MOTOR_HEAD_UP = 0x01
MOTOR_HEAD_DOWN = 0x02
MOTOR_FEET_UP = 0x04
MOTOR_FEET_DOWN = 0x08
MOTOR_PILLOW_UP = 0x10
MOTOR_PILLOW_DOWN = 0x20

# ---------------------------------------------------------------------------
# Preset commands (byte 24 of the command packet)
#
# Presets are "fire and forget" -- the bed moves to a saved position
# autonomously after receiving the command. The command is sent repeatedly
# (like the app does) but the bed handles the actual positioning.
#
# Vibration commands (also byte 24) are STATE TOGGLES: each command burst
# cycles through off → low → medium → high → off. One command = one state
# transition. This is why select.py must calculate the number of cycles needed.
# ---------------------------------------------------------------------------
PRESET_1 = 0x20
PRESET_2 = 0x40
PRESET_ZEROG = 0x10
PRESET_SLEEP = 0x80
PRESET_VIB_HEAD = 0x08      # Cycles head vibration state
PRESET_VIB_FEET = 0x04      # Cycles feet vibration state

# ---------------------------------------------------------------------------
# Extended commands (byte 26 of the command packet)
#
# Same behavior as presets -- bed moves to position autonomously.
# ---------------------------------------------------------------------------
EXT_FLAT = 0x08

# ---------------------------------------------------------------------------
# Vibration level mapping
#
# The bed reports vibration state as raw byte values in the status response.
# These map between the raw protocol values and human-readable names.
# The sequence is: 0=off, 1=low, 3=medium, 6=high (non-linear encoding).
# ---------------------------------------------------------------------------
VIB_LEVELS = {0: "off", 1: "low", 3: "medium", 6: "high"}
VIB_LEVEL_VALUES = {"off": 0, "low": 1, "medium": 3, "high": 6}
VIB_OPTIONS = ["off", "low", "medium", "high"]
