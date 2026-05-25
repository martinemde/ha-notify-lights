"""Config flow for the Notify Lights integration."""
from __future__ import annotations

import logging
import re
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

_LOGGER = logging.getLogger(__name__)

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


def _slugify(name: str) -> str:
    """Generate a stable slug from a notification name."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _notification_schema() -> vol.Schema:
    """Build the notification form schema (no targets — pool owns them)."""
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
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required("duration", default=0): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=86400, step=1,
                    unit_of_measurement="seconds",
                )
            ),
            vol.Required("priority", default=DEFAULT_PRIORITY): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100, step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        self._pool_name: str = ""
        self._area_id: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("name"): selector.TextSelector(),
                        vol.Optional("area_id", default=""): selector.AreaSelector(),
                    }
                ),
            )

        self._pool_name = user_input["name"]
        self._area_id = user_input.get("area_id", "")
        return await self.async_step_targets()

    async def async_step_targets(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is None:
            return self.async_show_form(
                step_id="targets",
                data_schema=vol.Schema(
                    {
                        vol.Required("targets"): selector.EntitySelector(
                            selector.EntitySelectorConfig(
                                domain=["light", "switch"],
                                multiple=True,
                            )
                        ),
                    }
                ),
            )

        _LOGGER.info("Creating pool %r with %d targets", self._pool_name, len(user_input["targets"]))
        return self.async_create_entry(
            title=self._pool_name,
            data={
                "name": self._pool_name,
                "area_id": self._area_id,
                "targets": user_input["targets"],
            },
            options={"notifications": {}},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> NotifyLightsOptionsFlow:
        return NotifyLightsOptionsFlow(config_entry)


class NotifyLightsOptionsFlow(OptionsFlowWithConfigEntry):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = self.options.get("notifications", {})

        if not notifications:
            return await self.async_step_add()

        menu_options = ["basics", "add", "modify", "delete"]
        return self.async_show_menu(step_id="init", menu_options=menu_options)

    async def async_step_basics(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            new_data = dict(self.config_entry.data)
            new_data["name"] = user_input["name"]
            new_data["area_id"] = user_input.get("area_id", "")
            new_data["targets"] = user_input["targets"]
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(data=dict(self.options))

        current = self.config_entry.data
        return self.async_show_form(
            step_id="basics",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=current.get("name", "")): selector.TextSelector(),
                    vol.Optional("area_id", default=current.get("area_id", "")): selector.AreaSelector(),
                    vol.Required("targets", default=current.get("targets", [])): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain=["light", "switch"],
                            multiple=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"]
            slug = _slugify(name)
            notifications = dict(self.options.get("notifications", {}))

            if slug in notifications:
                errors["name"] = "name_exists"
            else:
                notifications[slug] = {
                    "slug": slug,
                    "display_name": name,
                    "color": user_input["color"],
                    "effect": user_input["effect"],
                    "effect_speed": user_input["effect_speed"],
                    "brightness": int(user_input["brightness"]),
                    "duration": int(user_input["duration"]),
                    "priority": int(user_input["priority"]),
                }
                _LOGGER.info("Added notification %r (slug=%r)", name, slug)
                return self.async_create_entry(data={"notifications": notifications})

        return self.async_show_form(
            step_id="add",
            data_schema=_notification_schema(),
            errors=errors,
        )

    async def async_step_modify(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))

        if user_input is not None and "slug" in user_input:
            self._modify_slug = user_input["slug"]
            return await self.async_step_modify_form()

        slug_options = [
            selector.SelectOptionDict(value=slug, label=cfg["display_name"])
            for slug, cfg in notifications.items()
        ]

        return self.async_show_form(
            step_id="modify",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=slug_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_modify_form(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            notifications = dict(self.options.get("notifications", {}))
            slug = self._modify_slug
            notifications[slug] = {
                "slug": slug,
                "display_name": user_input["name"],
                "color": user_input["color"],
                "effect": user_input["effect"],
                "effect_speed": user_input["effect_speed"],
                "brightness": int(user_input["brightness"]),
                "duration": int(user_input["duration"]),
                "priority": int(user_input["priority"]),
            }
            _LOGGER.info("Modified notification slug=%r", slug)
            return self.async_create_entry(data={"notifications": notifications})

        current = self.options["notifications"][self._modify_slug]
        return self.async_show_form(
            step_id="modify_form",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=current["display_name"]): selector.TextSelector(),
                    vol.Required("color", default=current["color"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=COLOR_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("effect", default=current["effect"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=EFFECT_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("effect_speed", default=current["effect_speed"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SPEED_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required("brightness", default=current["brightness"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                    vol.Required("duration", default=current["duration"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=86400, step=1,
                            unit_of_measurement="seconds",
                        )
                    ),
                    vol.Required("priority", default=current["priority"]): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=100, step=1,
                            mode=selector.NumberSelectorMode.SLIDER,
                        )
                    ),
                }
            ),
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))

        if user_input is not None:
            slug = user_input["slug"]
            notifications.pop(slug, None)
            _LOGGER.info("Deleted notification slug=%r", slug)
            return self.async_create_entry(data={"notifications": notifications})

        slug_options = [
            selector.SelectOptionDict(value=slug, label=cfg["display_name"])
            for slug, cfg in notifications.items()
        ]

        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=slug_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )
