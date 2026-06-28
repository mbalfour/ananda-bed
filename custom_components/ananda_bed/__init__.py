"""Ananda Bed integration for Home Assistant.

This is the entry point for the custom integration. Home Assistant calls
async_setup_entry() when a user adds an Ananda bed via the UI (config flow),
and async_unload_entry() when the entry is removed or HA shuts down.

The integration controls Ananda adjustable bed bases (Keeson WF02D controller)
over a proprietary UDP protocol on port 5987. It exposes bed motors as Cover
entities, presets as Button entities, and vibration levels as Select entities.

Architecture:
    ConfigEntry → Coordinator (polls bed status every 30s)
                → Cover entities (head/feet motor position control)
                → Button entities (presets + pillow tilt)
                → Select entities (vibration level cycling)
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AnandaBedCoordinator

# Platforms that this integration provides entities for.
# Each platform module (cover.py, button.py, select.py) has its own
# async_setup_entry that creates the platform-specific entities.
PLATFORMS = ["cover", "button", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ananda Bed from a config entry.

    Called by Home Assistant when a config entry is loaded (at startup or
    when a new entry is created via the config flow). This function:
    1. Creates the DataUpdateCoordinator that manages bed communication
    2. Performs an initial status poll to populate entity state
    3. Stores the coordinator in hass.data for platform entities to access
    4. Forwards setup to each platform (cover, button, select)
    """
    coordinator = AnandaBedCoordinator(hass, entry.data)
    # First refresh populates coordinator.data with current bed status.
    # If this fails, HA will retry setup later (ConfigEntryNotReady).
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in hass.data keyed by entry_id so each platform's
    # async_setup_entry can retrieve it.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Called when the user removes the integration or HA is shutting down.
    Unloads all platform entities and removes the coordinator from hass.data.
    """
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
