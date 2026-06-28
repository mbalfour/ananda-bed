"""DataUpdateCoordinator for Ananda Bed.

This module implements the polling coordinator that periodically queries the
bed's current state (motor positions, vibration levels). It uses Home
Assistant's DataUpdateCoordinator pattern, which provides:
    - Scheduled polling at a fixed interval (30 seconds)
    - Automatic retry on failure with exponential backoff
    - Shared state: all entities read from coordinator.data, avoiding
      redundant network calls
    - Integration with HA's entity update lifecycle

The coordinator does NOT maintain a persistent connection to the bed. Each
poll uses the "connect-on-demand" pattern (see protocol.py): open a fresh
UDP session, send a status query, read the response, close the socket. This
allows peaceful coexistence with the official mobile app, which also expects
to be the sole active session.

Data Flow:
    Timer fires → _async_update_data() → send_command_and_get_status()
    → opens UDP session → discovery → auth → sends noop command → parses
    44-byte status response → returns dict → stored in self.data
    → all CoordinatorEntity instances see updated state
"""

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import CONF_AUTH_TOKEN, CONF_MAC, DOMAIN
from .protocol import send_command_and_get_status

_LOGGER = logging.getLogger(__name__)


class AnandaBedCoordinator(DataUpdateCoordinator):
    """Coordinator that polls bed status on a regular interval.

    Inherits from DataUpdateCoordinator which handles:
    - Scheduling periodic calls to _async_update_data
    - Notifying all registered entities when new data arrives
    - Rate-limiting refresh requests from multiple entities
    - Error handling and retry logic

    The coordinator stores the bed's MAC address and auth token (both as
    raw bytes) for use by the protocol layer during each poll.
    """

    def __init__(self, hass: HomeAssistant, entry_data: dict) -> None:
        super().__init__(
            hass, _LOGGER, name=DOMAIN, update_interval=timedelta(seconds=30),
        )
        # Convert hex string MAC to raw bytes for the protocol layer.
        # The MAC is 6 bytes that identify the specific bed on the network.
        mac_hex = entry_data[CONF_MAC]
        self._mac = bytes.fromhex(mac_hex)
        # Auth token is the 16-byte Xlink product access key.
        self._auth_token = bytes.fromhex(entry_data[CONF_AUTH_TOKEN])

    @property
    def mac(self) -> bytes:
        """Raw 6-byte MAC address for protocol operations."""
        return self._mac

    @property
    def auth_token(self) -> bytes:
        """Raw 16-byte auth token for protocol operations."""
        return self._auth_token

    async def _async_update_data(self) -> dict | None:
        """Poll the bed for current status.

        Sends a "noop" command (motor=0, preset=0) which causes the bed to
        respond with a full 44-byte status packet without moving any motors.
        This is the same technique the mobile app uses for status polling.

        Returns a dict with keys:
            head_position: int (0 to HEAD_MAX encoder ticks)
            feet_position: int (0 to FEET_MAX encoder ticks)
            head_vibration: int (0=off, 1=low, 3=medium, 6=high)
            feet_vibration: int (0=off, 1=low, 3=medium, 6=high)
            preset_active: bool (True if bed is currently executing a preset)

        Returns None if communication fails (bed offline, network issue, etc.)
        """
        status = await send_command_and_get_status(
            self._mac, self._auth_token, motor=0, preset=0,
        )
        if status is None:
            _LOGGER.debug("Failed to get status from bed")
        return status
