"""Config flow for Ananda Bed.

This module implements the Home Assistant config flow UI that allows users to
add an Ananda bed through the Integrations settings page. The flow collects:
    - A friendly name for the bed (default: "Ananda Bed")
    - The bed's MAC address (6 bytes hex, used for UDP discovery broadcasts)
    - An optional auth token (defaults to the universal Xlink product key)

The MAC address serves as the unique identifier for the bed on the network.
During discovery, the MAC is embedded in the broadcast packet so that only the
target bed responds. This allows multiple beds on the same LAN.

Home Assistant Architecture:
    ConfigFlow classes define multi-step UI wizards. Each step is an
    async_step_* method that either shows a form or creates an entry.
    The VERSION attribute tracks schema changes for migration support.
"""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME

from .const import CONF_AUTH_TOKEN, CONF_MAC, DEFAULT_AUTH_TOKEN, DOMAIN


class AnandaBedConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for setting up an Ananda bed.

    This is a single-step flow: the user provides the bed's MAC address and
    optional auth token, we validate the MAC format, then create the entry.
    No network connection is attempted during setup (the bed uses UDP broadcast
    discovery at runtime, so there's nothing to "test" without actually
    connecting).
    """

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial (and only) configuration step.

        Shows a form requesting the bed's MAC address and optional auth token.
        On submission, validates that the MAC is valid hex, normalizes it
        (strips colons/dashes), sets it as the unique ID to prevent duplicates,
        and creates the config entry.
        """
        errors = {}

        if user_input is not None:
            # Normalize MAC: strip common separators and whitespace
            mac = user_input[CONF_MAC].replace(":", "").replace("-", "").strip()
            try:
                # Validate that the MAC is valid hexadecimal
                bytes.fromhex(mac)
            except ValueError:
                errors[CONF_MAC] = "invalid_mac"

            if not errors:
                # Store normalized MAC (no separators, just hex digits)
                user_input[CONF_MAC] = mac
                # Use MAC as unique_id to prevent adding the same bed twice
                await self.async_set_unique_id(mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input,
                )

        # Show the configuration form.
        # vol.Schema defines the form fields and their types/defaults.
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="Ananda Bed"): str,
                vol.Required(CONF_MAC): str,
                # Auth token defaults to the universal Xlink key -- users only
                # need to change this if they have a non-standard firmware.
                vol.Optional(CONF_AUTH_TOKEN, default=DEFAULT_AUTH_TOKEN): str,
            }),
            errors=errors,
        )
