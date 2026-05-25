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
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    selector,
)

from .adapter import AdapterRegistry
from .adapters.inovelli_blue_z2m import InovelliBlueZ2MAdapter
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

def _build_notification_schema(
    target_entity_ids: list[str] | None = None,
) -> vol.Schema:
    """Build the notification form schema.

    When target_entity_ids is provided, constrains the target picker
    to only entities whose devices match a registered adapter.
    """
    if target_entity_ids:
        target_options = [
            selector.SelectOptionDict(value=eid, label=eid)
            for eid in sorted(target_entity_ids)
        ]
        targets_selector = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=target_options,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    else:
        targets_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["light", "switch"],
                multiple=True,
            )
        )

    return vol.Schema(
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
            vol.Required("targets"): targets_selector,
        }
    )


def _find_supported_entities(hass) -> list[str]:
    """Return entity IDs whose devices match a registered adapter."""
    entity_reg = er.async_get(hass)
    device_reg = dr.async_get(hass)

    registry = AdapterRegistry()
    registry.register(InovelliBlueZ2MAdapter(hass))

    result = []
    for entity_entry in entity_reg.entities.values():
        if entity_entry.domain not in ("light", "switch"):
            continue
        if entity_entry.device_id is None:
            continue
        device_entry = device_reg.async_get(entity_entry.device_id)
        if device_entry is None:
            continue
        adapter = registry.get_adapter(
            device_entry.manufacturer or "", device_entry.model or ""
        )
        if adapter is not None:
            result.append(entity_entry.entity_id)

    _LOGGER.debug("Supported target entities: %s", result)
    return result


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

        supported = _find_supported_entities(self.hass)
        schema = _build_notification_schema(supported or None)

        return self.async_show_form(
            step_id="add",
            data_schema=schema,
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
