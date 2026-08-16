"""Config flow for the Notify Lights integration.

A config entry is a *catalog* of notifications. Each notification carries its
own targets, so it is a complete, self-describing thing: name, meaning,
appearance, priority, and where it shows.

Targets live on the notification rather than on the entry because notification
entities cannot take call-time target parameters -- so the definition is the
only place targets can live. The earlier "pool owns the targets" model forced
the same notification to be redefined once per pool, and those copies drifted.
"""
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

TARGET_ENTITY_FILTER = selector.EntityFilterSelectorConfig(
    domain=["light", "switch"],
)


def _slugify(name: str) -> str:
    """Generate a stable slug from a notification name."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _target_selector() -> selector.TargetSelector:
    """A selector accepting any mix of entities, devices and areas."""
    return selector.TargetSelector(
        selector.TargetSelectorConfig(entity=[TARGET_ENTITY_FILTER])
    )


def notification_config(slug: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Build the stored notification config from submitted form data."""
    return {
        "slug": slug,
        "display_name": user_input["name"],
        "description": user_input.get("description", ""),
        "targets": user_input.get("targets", {}),
        "exclude": user_input.get("exclude", {}),
        "color": user_input["color"],
        "effect": user_input["effect"],
        "effect_speed": user_input["effect_speed"],
        "brightness": int(user_input["brightness"]),
        "duration": int(user_input["duration"]),
        "priority": int(user_input["priority"]),
        "state_entity": user_input.get("state_entity") or None,
        "active_state": user_input.get("active_state", "on"),
    }


def _notification_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the add/modify form schema, pre-filled from `defaults`.

    Used for both steps so the two forms cannot drift apart.
    """
    current = defaults or {}
    name_key = (
        vol.Required("name", default=current["display_name"])
        if "display_name" in current
        else vol.Required("name")
    )

    return vol.Schema(
        {
            name_key: selector.TextSelector(),
            # What this notification means. display_name doubles as the UI
            # label, so it cannot carry a sentence; this is what makes the
            # catalog readable months later.
            vol.Optional(
                "description", default=current.get("description", "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
            # Where it shows. Entities, devices and areas may be mixed; group
            # entities are expanded to their members downstream, so a single
            # area light group covers a whole room and keeps working as
            # switches are added to it.
            vol.Required(
                "targets", default=current.get("targets", {})
            ): _target_selector(),
            # Subtracted from targets. This is what makes "the whole house
            # except the kids' rooms" expressible without enumerating every
            # switch that should light up.
            vol.Optional(
                "exclude", default=current.get("exclude", {})
            ): _target_selector(),
            vol.Required(
                "color", default=current.get("color", "blue")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=COLOR_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "effect", default=current.get("effect", Effect.SOLID)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=EFFECT_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "effect_speed", default=current.get("effect_speed", DEFAULT_SPEED)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SPEED_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "brightness", default=current.get("brightness", DEFAULT_BRIGHTNESS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            # 0 makes the notification stateful: a source-bound binary sensor
            # or, without a source, a manual switch. Anything else creates a
            # momentary button that clears itself after this many seconds.
            vol.Required(
                "duration", default=current.get("duration", 0)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=86400,
                    step=1,
                    unit_of_measurement="seconds",
                )
            ),
            # Optional direct state binding. With duration 0 this replaces the
            # manual switch with a read-only notification binary sensor.
            vol.Optional(
                "state_entity", default=current.get("state_entity") or ""
            ): selector.EntitySelector(),
            vol.Required(
                "active_state", default=current.get("active_state", "on")
            ): selector.TextSelector(),
            vol.Required(
                "priority", default=current.get("priority", DEFAULT_PRIORITY)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            "name", default="Notify Lights"
                        ): selector.TextSelector(),
                    }
                ),
            )

        name = user_input["name"]
        _LOGGER.info("Creating notification catalog %r", name)
        return self.async_create_entry(
            title=name,
            data={"name": name},
            options={"notifications": {}},
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> NotifyLightsOptionsFlow:
        return NotifyLightsOptionsFlow(config_entry)


class NotifyLightsOptionsFlow(OptionsFlowWithConfigEntry):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = self.options.get("notifications", {})

        if not notifications:
            return await self.async_step_add()

        return self.async_show_menu(
            step_id="init", menu_options=["add", "modify", "delete"]
        )

    async def async_step_add(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}

        if user_input is not None:
            name = user_input["name"]
            slug = _slugify(name)
            notifications = dict(self.options.get("notifications", {}))

            if user_input.get("state_entity") and int(user_input["duration"]) != 0:
                errors["duration"] = "state_source_requires_zero_duration"
            elif slug in notifications:
                errors["name"] = "name_exists"
            else:
                notifications[slug] = notification_config(slug, user_input)
                _LOGGER.info("Added notification %r (slug=%r)", name, slug)
                return self.async_create_entry(
                    data={"notifications": notifications}
                )

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

        return self.async_show_form(
            step_id="modify",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_slug_options(notifications),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_modify_form(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        slug = self._modify_slug
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get("state_entity") and int(user_input["duration"]) != 0:
                errors["duration"] = "state_source_requires_zero_duration"
            else:
                notifications = dict(self.options.get("notifications", {}))
                # Keep the original slug so the entity_id survives a rename of
                # the display name -- callers reference the entity, not label.
                notifications[slug] = notification_config(slug, user_input)
                _LOGGER.info("Modified notification slug=%r", slug)
                return self.async_create_entry(
                    data={"notifications": notifications}
                )

        return self.async_show_form(
            step_id="modify_form",
            data_schema=_notification_schema(
                self.options["notifications"][slug]
            ),
            errors=errors,
        )

    async def async_step_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self.options.get("notifications", {}))

        if user_input is not None:
            slug = user_input["slug"]
            notifications.pop(slug, None)
            _LOGGER.info("Deleted notification slug=%r", slug)
            return self.async_create_entry(
                data={"notifications": notifications}
            )

        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema(
                {
                    vol.Required("slug"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=_slug_options(notifications),
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )


def _slug_options(notifications: dict[str, Any]) -> list:
    """Dropdown options listing notifications by their display name."""
    return [
        selector.SelectOptionDict(value=slug, label=cfg["display_name"])
        for slug, cfg in notifications.items()
    ]
