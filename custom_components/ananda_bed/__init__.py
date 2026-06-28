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

import logging
import pathlib

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import AnandaBedCoordinator

_LOGGER = logging.getLogger(__name__)

# Path to the frontend card JS file.
FRONTEND_DIR = pathlib.Path(__file__).parent / "frontend"
CARD_JS_PATH = str(FRONTEND_DIR / "ananda-bed-card.js")
CARD_JS_URL = f"/{DOMAIN}/ananda-bed-card.js"

# Platforms that this integration provides entities for.
# Each platform module (cover.py, button.py, select.py) has its own
# async_setup_entry that creates the platform-specific entities.
PLATFORMS = ["cover", "button", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Ananda Bed from a config entry.

    Called by Home Assistant when a config entry is loaded (at startup or
    when a new entry is created via the config flow). This function:
    1. Registers the custom Lovelace card frontend resource (once)
    2. Creates the DataUpdateCoordinator that manages bed communication
    3. Performs an initial status poll to populate entity state
    4. Stores the coordinator in hass.data for platform entities to access
    5. Forwards setup to each platform (cover, button, select)
    """
    # Register the custom Lovelace card JS (idempotent; safe to call multiple times).
    hass.http.register_static_path(CARD_JS_URL, CARD_JS_PATH, cache_headers=False)
    add_extra_js_url(hass, CARD_JS_URL)

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
