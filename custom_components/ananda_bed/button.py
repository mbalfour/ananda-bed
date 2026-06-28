"""Button entities for Ananda Bed presets and pillow tilt.

=============================================================================
PRESET vs MOTOR BUTTONS -- KEY DIFFERENCES
=============================================================================

This module exposes two distinct types of button entities:

1. PRESET BUTTONS (AnandaPresetButton):
   - Fire-and-forget commands: the bed autonomously moves to a saved position
   - Implemented via send_command_and_get_status() -- single command packet
   - The bed handles all motor control internally until position is reached
   - Includes: Flat, Preset 1, Preset 2 (TV), Zero Gravity, Anti-Snore
   - Protocol: preset byte (byte 24) or ext byte (byte 26) in command packet

2. PILLOW MOTOR BUTTONS (AnandaPillowButton):
   - Continuous motor commands: motor only runs while packets are being sent
   - Implemented via run_motor_command() -- sends at 4Hz for 1 second
   - The motor stops immediately when we stop sending packets
   - Includes: Pillow Up, Pillow Down
   - Protocol: motor byte (byte 23) in command packet
   - Unlike head/feet, the pillow motor has NO position feedback (no encoder),
     so it cannot be a Cover entity. Button with fixed 1s duration is the
     best available UX -- user presses repeatedly to adjust.

=============================================================================
WHY BUTTONS AND NOT OTHER ENTITY TYPES?
=============================================================================

Presets are momentary actions with no state to track (they trigger movement
but there's no "preset 1 is active" persistent state worth exposing). HA's
Button entity is designed for exactly this: stateless "do something" actions.

Pillow tilt similarly has no position feedback, making it unsuitable for
Cover (which requires position reporting) or Number (no value to display).
"""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    EXT_FLAT,
    MOTOR_PILLOW_DOWN,
    MOTOR_PILLOW_UP,
    PRESET_1,
    PRESET_2,
    PRESET_SLEEP,
    PRESET_ZEROG,
)
from .coordinator import AnandaBedCoordinator
from .protocol import run_motor_command, send_command_and_get_status

# Preset button definitions: (key, display_name, command_kwargs)
# command_kwargs are passed directly to send_command_and_get_status().
# Note: "Flat" uses the ext= kwarg (byte 26) while others use preset= (byte 24).
PRESET_BUTTONS = [
    ("flat", "Flat", {"ext": EXT_FLAT}),
    ("preset1", "Preset 1", {"preset": PRESET_1}),
    ("preset2", "Preset 2 (TV)", {"preset": PRESET_2}),
    ("zerog", "Zero Gravity", {"preset": PRESET_ZEROG}),
    ("sleep", "Anti-Snore", {"preset": PRESET_SLEEP}),
]

# Pillow motor button definitions: (key, display_name, motor_command_byte)
# These use motor byte (byte 23) with continuous 4Hz sending for 1 second.
PILLOW_BUTTONS = [
    ("pillow_up", "Pillow Up", MOTOR_PILLOW_UP),
    ("pillow_down", "Pillow Down", MOTOR_PILLOW_DOWN),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up button entities for this bed.

    Creates preset buttons (fire-and-forget position commands) and pillow
    motor buttons (timed continuous motor commands).
    """
    coordinator: AnandaBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ButtonEntity] = []

    for key, name, cmd_kwargs in PRESET_BUTTONS:
        entities.append(AnandaPresetButton(coordinator, entry, key, name, cmd_kwargs))
    for key, name, motor in PILLOW_BUTTONS:
        entities.append(AnandaPillowButton(coordinator, entry, key, name, motor))

    async_add_entities(entities)


class AnandaPresetButton(ButtonEntity):
    """Button that fires a preset command (fire-and-forget).

    When pressed, sends a single command packet with the preset byte set.
    The bed autonomously moves to the saved position -- no further packets
    needed. After sending, triggers a coordinator refresh so position
    entities update as the bed moves.

    These buttons are NOT CoordinatorEntity because they have no state to
    display -- they're purely action triggers.
    """

    def __init__(self, coordinator: AnandaBedCoordinator, entry: ConfigEntry,
                 key: str, name: str, cmd_kwargs: dict):
        self._coordinator = coordinator
        self._cmd_kwargs = cmd_kwargs
        self._attr_name = f"{entry.title} {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    async def async_press(self) -> None:
        """Handle button press: send preset command and refresh state."""
        await send_command_and_get_status(
            self._coordinator.mac, self._coordinator.auth_token, **self._cmd_kwargs,
        )
        await self._coordinator.async_request_refresh()


class AnandaPillowButton(ButtonEntity):
    """Button that fires a pillow motor for 1 second (continuous command).

    Unlike presets, motor commands require CONTINUOUS packet sending at 4Hz
    -- the motor only runs while it's receiving packets. Each button press
    runs the pillow motor for exactly 1 second (4 packets), then stops.

    The pillow motor has no position encoder, so there's no way to implement
    precise positioning. The user presses the button multiple times to reach
    the desired tilt angle.
    """

    def __init__(self, coordinator: AnandaBedCoordinator, entry: ConfigEntry,
                 key: str, name: str, motor_byte: int):
        self._coordinator = coordinator
        self._motor_byte = motor_byte
        self._attr_name = f"{entry.title} {name}"
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    async def async_press(self) -> None:
        """Handle button press: run pillow motor for 1 second, then stop."""
        await run_motor_command(
            self._coordinator.mac, self._coordinator.auth_token,
            self._motor_byte, duration_sec=1.0,
        )
        await self._coordinator.async_request_refresh()
