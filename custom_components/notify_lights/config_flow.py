"""Config flow for the Notify Lights integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlowWithConfigEntry,
)
from homeassistant.helpers import selector

from .const import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_PRIORITY,
    DEFAULT_SPEED,
    DOMAIN,
    Effect,
    NAMED_COLORS,
    Speed,
)

COLOR_OPTIONS = [
    selector.SelectOptionDict(value=name, label=name.capitalize())
    for name in NAMED_COLORS
]

EFFECT_OPTIONS = [
    selector.SelectOptionDict(value=e.value, label=e.value.capitalize())
    for e in Effect
]

SPEED_OPTIONS = [
    selector.SelectOptionDict(value=s.value, label=s.value.capitalize())
    for s in Speed
]

NOTIFICATION_SCHEMA = vol.Schema(
    {
        vol.Required("name"): selector.TextSelector(),
        vol.Required("color", default="blue"): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=COLOR_OPTIONS,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required("effect", default=Effect.SOLID): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=EFFECT_OPTIONS,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required("effect_speed", default=DEFAULT_SPEED): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=SPEED_OPTIONS,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required("brightness", default=DEFAULT_BRIGHTNESS): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required("duration", default=0): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=86400, step=1, unit_of_measurement="seconds")
        ),
        vol.Required("priority", default=DEFAULT_PRIORITY): selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100, step=1, mode=selector.NumberSelectorMode.SLIDER)
        ),
        vol.Required("targets"): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["light", "switch"],
                multiple=True,
            )
        ),
    }
)


_LOGGER = logging.getLogger(__name__)


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        _LOGGER.debug("Config flow user step: input=%s", user_input)
        if user_input is None:
            return self.async_show_form(step_id="user")

        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        _LOGGER.info("Creating config entry for Notify Lights")
        return self.async_create_entry(
            title="Notify Lights",
            data={},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> NotifyLightsOptionsFlow:
        return NotifyLightsOptionsFlow(config_entry)


class NotifyLightsOptionsFlow(OptionsFlowWithConfigEntry):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))
        _LOGGER.debug(
            "Options flow init: %d existing notifications, input=%s",
            len(notifications), user_input,
        )

        if not notifications:
            return await self.async_step_add()

        menu_options = ["add", "remove"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        _LOGGER.debug("Options flow add step: input=%s", user_input)

        if user_input is not None:
            name = user_input["name"]
            notifications = dict(self.options.get("notifications", {}))

            if name in notifications:
                _LOGGER.warning("Notification name %r already exists", name)
                errors["name"] = "name_exists"
            else:
                notifications[name] = user_input
                _LOGGER.info(
                    "Adding notification %r, saving %d total: %s",
                    name, len(notifications), list(notifications.keys()),
                )
                return self.async_create_entry(data={"notifications": notifications})

        return self.async_show_form(
            step_id="add",
            data_schema=NOTIFICATION_SCHEMA,
            errors=errors,
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))
        _LOGGER.debug(
            "Options flow remove step: input=%s, existing=%s",
            user_input, list(notifications.keys()),
        )

        if user_input is not None:
            name = user_input["name"]
            notifications.pop(name, None)
            _LOGGER.info(
                "Removed notification %r, %d remaining: %s",
                name, len(notifications), list(notifications.keys()),
            )
            return self.async_create_entry(data={"notifications": notifications})

        name_options = [
            selector.SelectOptionDict(value=name, label=name)
            for name in notifications
        ]

        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {
                    vol.Required("name"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=name_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
