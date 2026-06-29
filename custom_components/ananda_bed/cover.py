"""Cover entities for Ananda Bed head and feet motors.

=============================================================================
WHY COVER ENTITIES FOR A BED?
=============================================================================

Home Assistant's Cover entity is designed for things that move between open
(100%) and closed (0%) -- blinds, garage doors, curtains. An adjustable bed
motor has the exact same semantics:
    - 0% = fully flat (closed/down)
    - 100% = fully raised (open/up)
    - Supports continuous movement (open, close, stop)
    - Supports set_position for precise percentage targeting

There is no "Bed" entity type in HA, and Cover provides the richest UI
controls (position slider, up/down/stop buttons) out of all standard entity
types. Using CoverDeviceClass.BLIND gives a neutral icon.

=============================================================================
POSITION MAPPING
=============================================================================

The bed reports motor positions as raw encoder ticks:
    Head: 0 (flat) to 21138 (fully raised)
    Feet: 0 (flat) to 8924 (fully raised)

HA Cover expects 0-100 integer percentage. Conversion:
    HA position = round(ticks * 100 / MAX_TICKS)
    Target ticks = position * MAX_TICKS / 100

The protocol module (run_motor_to_position) handles closed-loop control:
it continuously sends motor commands while monitoring position feedback,
stopping when within 1% of the target.

=============================================================================
ARCHITECTURE
=============================================================================

Each AnandaBedCover is a CoordinatorEntity -- it reads its state from the
shared AnandaBedCoordinator.data dict (populated every 30s by polling).
Commands (open/close/set_position) use the protocol layer directly and then
trigger a coordinator refresh to update all entities with the new state.
"""

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    FEET_MAX,
    HEAD_MAX,
    MOTOR_FEET_DOWN,
    MOTOR_FEET_UP,
    MOTOR_HEAD_DOWN,
    MOTOR_HEAD_UP,
)
from .coordinator import AnandaBedCoordinator
from .protocol import run_motor_to_position, send_command_and_get_status


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up cover entities for this bed.

    Creates two Cover entities per bed:
        - Head: controls the head section motor
        - Feet: controls the feet section motor

    Note: The pillow tilt motor has no position feedback, so it's exposed
    as a Button entity instead (see button.py).
    """
    coordinator: AnandaBedCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        AnandaBedCover(coordinator, entry, "head"),
        AnandaBedCover(coordinator, entry, "feet"),
    ])


class AnandaBedCover(CoordinatorEntity, CoverEntity):
    """Cover entity representing a bed motor (head or feet).

    Inherits from:
        CoordinatorEntity: Automatically updates state when coordinator
            refreshes (every 30s or after explicit refresh request)
        CoverEntity: Provides the HA Cover interface (position, open/close/stop)

    The device_class is BLIND (neutral icon, no special semantics).
    Supported features: OPEN, CLOSE, STOP, SET_POSITION (full control).
    """

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE |
        CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: AnandaBedCoordinator, entry: ConfigEntry, section: str):
        super().__init__(coordinator)
        self._section = section  # "head" or "feet"
        self._attr_name = f"{entry.title} {section.title()}"
        self._attr_unique_id = f"{entry.entry_id}_{section}"
        self._moving = False  # Track if we're currently commanding movement
        self._target_position = None  # Target % during movement
        self._cancel_event = None  # asyncio.Event to signal movement cancellation

    @property
    def extra_state_attributes(self):
        """Expose target position so the UI card can show it during movement."""
        attrs = {}
        if self._target_position is not None:
            attrs["target_position"] = self._target_position
        return attrs

    @property
    def current_cover_position(self) -> int | None:
        """Return current position as 0-100% (0=flat, 100=fully raised).

        Reads raw encoder ticks from coordinator data and converts to
        percentage using the appropriate MAX value for this motor section.
        Returns None if no data is available (bed unreachable).
        """
        if not self.coordinator.data:
            return None
        max_val = HEAD_MAX if self._section == "head" else FEET_MAX
        ticks = self.coordinator.data[f"{self._section}_position"]
        # Cap at 100% in case encoder overshoots slightly
        return min(100, round(ticks * 100 / max_val))

    @property
    def is_closed(self) -> bool:
        """Cover is "closed" (flat) when position is 0%."""
        return self.current_cover_position == 0

    @property
    def is_opening(self) -> bool:
        """True while we're commanding upward movement."""
        return self._moving

    @property
    def is_closing(self) -> bool:
        """True while we're commanding downward movement."""
        return self._moving

    async def async_open_cover(self, **kwargs) -> None:
        """Fully raise this section (go to 100%)."""
        await self.async_set_cover_position(position=100)

    async def async_close_cover(self, **kwargs) -> None:
        """Fully lower this section (go to 0% / flat)."""
        await self.async_set_cover_position(position=0)

    async def async_stop_cover(self, **kwargs) -> None:
        """Stop motor movement immediately.

        Signals any in-progress movement to cancel, then sends a stop command
        to the bed and refreshes state.
        """
        # Signal the movement loop to stop
        if self._cancel_event:
            self._cancel_event.set()
        self._moving = False
        self._target_position = None
        self.async_write_ha_state()
        await send_command_and_get_status(
            self.coordinator.mac, self.coordinator.auth_token,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_cover_position(self, **kwargs) -> None:
        """Move this section to a specific position (0-100%).

        Determines the direction (up or down) by comparing current position
        to target, then delegates to run_motor_to_position() which implements
        closed-loop control (continuously sends motor command while monitoring
        position feedback, stopping when within 1% of target).

        The movement is blocking (awaited) -- HA's executor handles concurrency.
        After movement completes, triggers a coordinator refresh.
        """
        position = kwargs["position"]
        is_head = self._section == "head"

        # Cancel any in-progress movement first
        if self._cancel_event:
            self._cancel_event.set()

        # Select the correct motor command byte based on direction
        motor_up = MOTOR_HEAD_UP if is_head else MOTOR_FEET_UP
        motor_down = MOTOR_HEAD_DOWN if is_head else MOTOR_FEET_DOWN

        current = self.current_cover_position
        if current is None:
            return
        # Determine direction: raise if target is above current, lower otherwise
        motor_byte = motor_up if position > current else motor_down
        if position == current:
            return

        # Create a new cancel event for this movement
        import asyncio
        self._cancel_event = asyncio.Event()

        # Mark as moving and notify HA to update the UI (shows moving state)
        self._moving = True
        self._target_position = position
        self.async_write_ha_state()

        # Closed-loop movement: sends motor command at 4Hz while monitoring
        # position, stops within 1% of target or after 60s timeout.
        # The on_progress callback updates coordinator data in real-time
        # so the UI shows intermediate positions during movement.
        def _on_progress(status):
            self.coordinator.async_set_updated_data(status)

        await run_motor_to_position(
            self.coordinator.mac, self.coordinator.auth_token,
            motor_byte, position, is_head,
            on_progress=_on_progress,
            cancel_event=self._cancel_event,
        )

        # Movement complete -- update state and refresh coordinator
        self._moving = False
        self._target_position = None
        await self.coordinator.async_request_refresh()
