"""Select entities for Ananda Bed vibration levels.

=============================================================================
VIBRATION CYCLING LOGIC
=============================================================================

The bed's vibration control is unusual: there is NO "set level" command.
Instead, each vibration command packet CYCLES the state to the next level:

    off → low → medium → high → off → low → ...

This is a hardware limitation of the protocol -- the mobile app works the
same way (each tap cycles to the next state).

To implement HA's Select entity (which requires "jump to any option"), we:
    1. Read the CURRENT vibration level from coordinator data
    2. Calculate how many cycle steps are needed to reach the TARGET level
    3. Send that many command packets (each one advances the state by one step)

Example: Current = "low" (index 1), Target = "high" (index 3)
    Cycles needed = (3 - 1) % 4 = 2
    Send 2 vibration commands → low → medium → high ✓

Example: Current = "high" (index 3), Target = "low" (index 1)
    Cycles needed = (1 - 3) % 4 = 2
    Send 2 commands → high → off → low ✓ (wraps around through off)

The modulo arithmetic handles the circular wrapping automatically. Each
send_command_and_get_status() call opens a fresh UDP session (connect-on-
demand pattern), so multiple cycles each pay the ~1s handshake cost.

=============================================================================
STATUS BYTE VALUES
=============================================================================

The vibration level in status responses uses non-linear encoding:
    0 = off, 1 = low, 3 = medium, 6 = high

VIB_LEVELS maps these raw bytes to human-readable option names.
The cycling order is always: off → low → medium → high regardless of the
numeric gaps in the encoding.
"""

import asyncio

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COMMAND_RATE,
    DOMAIN,
    PRESET_VIB_FEET,
    PRESET_VIB_HEAD,
    VIB_LEVELS,
    VIB_LEVEL_VALUES,
    VIB_OPTIONS,
)
from .coordinator import AnandaBedCoordinator
from .protocol import AnandaUDPSession
from .protocol import send_command_and_get_status, AnandaUDPSession


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up vibration select entities for this bed.

    Creates two Select entities per bed:
        - Head Vibration: cycles the head vibration motor
        - Feet Vibration: cycles the feet vibration motor

    Each uses its own preset byte (PRESET_VIB_HEAD or PRESET_VIB_FEET)
    in the command packet's byte 24 slot.
    """
    coordinator: AnandaBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        AnandaVibrationSelect(coordinator, entry, "head", PRESET_VIB_HEAD),
        AnandaVibrationSelect(coordinator, entry, "feet", PRESET_VIB_FEET),
    ])


class AnandaVibrationSelect(CoordinatorEntity, SelectEntity):
    """Select entity for vibration level (cycles through levels via protocol).

    Inherits from:
        CoordinatorEntity: Reads current vibration state from coordinator data
            (updated every 30s by polling)
        SelectEntity: Provides dropdown UI with options ["off","low","medium","high"]

    The key challenge is that the protocol only supports CYCLING (not direct
    set), so async_select_option must calculate the minimum number of cycles
    to reach the desired state from the current state.
    """

    _attr_options = VIB_OPTIONS  # ["off", "low", "medium", "high"]

    def __init__(self, coordinator: AnandaBedCoordinator, entry: ConfigEntry,
                 section: str, preset_byte: int):
        super().__init__(coordinator)
        self._section = section          # "head" or "feet"
        self._preset_byte = preset_byte  # Protocol byte to send (0x08 or 0x04)
        self._attr_name = f"{entry.title} {section.title()} Vibration"
        self._attr_unique_id = f"{entry.entry_id}_vib_{section}"

    @property
    def current_option(self) -> str | None:
        """Return current vibration level as a human-readable string.

        Reads the raw byte value from coordinator data and maps it through
        VIB_LEVELS: {0: "off", 1: "low", 3: "medium", 6: "high"}.
        Returns None if no data available (bed unreachable).
        """
        if not self.coordinator.data:
            return None
        raw = self.coordinator.data[f"{self._section}_vibration"]
        return VIB_LEVELS.get(raw, "off")

    async def async_select_option(self, option: str) -> None:
        """Cycle vibration until we reach the desired level.

        The protocol only supports cycling: each command advances the state
        by one step in the fixed sequence [off, low, medium, high, off, ...].

        Algorithm:
            1. Determine current index in the cycle (0=off, 1=low, 2=med, 3=high)
            2. Determine target index
            3. Compute cycles needed = (target - current) % 4
            4. Send that many vibration commands

        Each send_command_and_get_status() opens a new UDP session, sends the
        vibration preset byte, and closes. This is unavoidable due to the
        connect-on-demand pattern and the cycling nature of the control.
        """
        current = self.current_option or "off"
        if current == option:
            return

        # Calculate minimum cycles needed using modular arithmetic.
        # The order list has 4 elements, so modulo 4 wraps correctly.
        order = VIB_OPTIONS  # ["off", "low", "medium", "high"]
        current_idx = order.index(current) if current in order else 0
        target_idx = order.index(option) if option in order else 0
        cycles = (target_idx - current_idx) % 4

        # Send one vibration command per cycle step needed.
        # Each cycle step requires a burst of commands (like holding the button)
        # to register as a single toggle. We send multiple packets per session.
        for _ in range(cycles):
            session = AnandaUDPSession(self.coordinator.mac, self.coordinator.auth_token)
            try:
                if not await session.connect():
                    break
                # Send a burst of commands (mimics holding the button briefly)
                for _ in range(6):
                    await session.send_command_no_wait(preset=self._preset_byte)
                    await asyncio.sleep(COMMAND_RATE)
                # Get status after the burst to update UI with new vibration state
                status = await session.get_status()
                if status:
                    self.coordinator.async_set_updated_data(status)
                # Brief pause between cycles for the bed to register the state change
                await asyncio.sleep(0.3)
            finally:
                session.close()

        # Refresh coordinator to update displayed state
        await self.coordinator.async_request_refresh()
