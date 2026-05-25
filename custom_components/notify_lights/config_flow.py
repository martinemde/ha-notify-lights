"""Config flow for the Notify Lights integration."""
from homeassistant.config_entries import ConfigFlow

from .const import DOMAIN


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup config flow for Notify Lights.

    Creates the integration's config entry. Notifications are managed
    separately via service calls after the entry is established.
    """

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Show a confirmation form, then create the config entry."""
        if user_input is None:
            return self.async_show_form(step_id="user")

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="Notify Lights",
            data={},
        )
