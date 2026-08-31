"""Config and options flows for Notify Lights.

The options flow deliberately speaks in two concepts:

* light groups are reusable routes such as "whole house except kids"; and
* notification rules say when, what, and which light groups.

Activation is selected explicitly. Duration is never used as a hidden type
switch in the UI, even though the compact stored/runtime model still represents
"while" rules with duration zero and timed rules with a positive duration.
"""

from __future__ import annotations

import logging
import re
from copy import deepcopy
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DEFAULT_BRIGHTNESS,
    DEFAULT_PRIORITY,
    DEFAULT_SPEED,
    DOMAIN,
    NAMED_COLORS,
    Activation,
    DisplayMode,
    Effect,
    Speed,
)

_LOGGER = logging.getLogger(__name__)

COLOR_OPTIONS = [
    selector.SelectOptionDict(value=name, label=name.capitalize())
    for name in NAMED_COLORS
]
EFFECT_OPTIONS = [
    selector.SelectOptionDict(value=effect.value, label=effect.value.capitalize())
    for effect in Effect
]
SPEED_OPTIONS = [
    selector.SelectOptionDict(value=speed.value, label=speed.value.capitalize())
    for speed in Speed
]
ACTIVATION_OPTIONS = [
    selector.SelectOptionDict(
        value=Activation.STATE_WHILE,
        label="Show while an entity is in a state",
    ),
    selector.SelectOptionDict(
        value=Activation.STATE_ENTERED,
        label="Show for a time when an entity enters a state",
    ),
    selector.SelectOptionDict(
        value=Activation.MANUAL_WHILE,
        label="Manual, stays on until turned off",
    ),
    selector.SelectOptionDict(
        value=Activation.MANUAL_TIMED,
        label="Manual, turns off after a time",
    ),
]
DISPLAY_MODE_OPTIONS = [
    selector.SelectOptionDict(
        value=DisplayMode.FULL,
        label="Full light bar",
    ),
    selector.SelectOptionDict(
        value=DisplayMode.INDICATOR,
        label="One-pixel indicator at the bottom",
    ),
]
SOURCE_STATE = "__state__"

TARGET_ENTITY_FILTER = selector.EntityFilterSelectorConfig(
    domain=["light", "switch"],
)


def _slugify(name: str) -> str:
    """Generate a stable slug from a record name."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _target_selector() -> selector.TargetSelector:
    """Accept any mix of light/switch entities, devices, and areas."""
    return selector.TargetSelector(
        selector.TargetSelectorConfig(entity=[TARGET_ENTITY_FILTER])
    )


def _activation_for_config(config: dict[str, Any]) -> Activation:
    """Return an explicit activation mode, including for pre-v3 configs."""
    if activation := config.get("activation"):
        return Activation(activation)
    if config.get("state_entity"):
        return (
            Activation.STATE_ENTERED
            if int(config.get("duration", 0)) > 0
            else Activation.STATE_WHILE
        )
    return (
        Activation.MANUAL_TIMED
        if int(config.get("duration", 0)) > 0
        else Activation.MANUAL_WHILE
    )


def notification_config(slug: str, draft: dict[str, Any]) -> dict[str, Any]:
    """Build one stored notification from the multi-step form draft."""
    activation = Activation(draft.get("activation") or _activation_for_config(draft))
    uses_source = activation in {
        Activation.STATE_WHILE,
        Activation.STATE_ENTERED,
    }
    is_timed = activation in {
        Activation.STATE_ENTERED,
        Activation.MANUAL_TIMED,
    }
    return {
        "slug": slug,
        "display_name": draft["name"],
        "description": draft.get("description", ""),
        "activation": activation.value,
        "groups": list(draft.get("groups", [])),
        "targets": draft.get("targets", {}),
        "exclude": draft.get("exclude", {}),
        "color": draft["color"],
        "effect": draft["effect"],
        "effect_speed": draft["effect_speed"],
        "brightness": int(draft["brightness"]),
        "duration": int(draft.get("duration", 300)) if is_timed else 0,
        "priority": int(draft["priority"]),
        "state_entity": draft.get("state_entity") if uses_source else None,
        "active_state": draft.get("active_state", "on") if uses_source else "on",
        "state_attribute": draft.get("state_attribute") if uses_source else None,
        "display_mode": draft.get("display_mode", DisplayMode.FULL),
    }


def _group_config(slug: str, user_input: dict[str, Any]) -> dict[str, Any]:
    """Build one reusable light group."""
    return {
        "slug": slug,
        "display_name": user_input["name"],
        "description": user_input.get("description", ""),
        "targets": user_input["targets"],
        "exclude": user_input.get("exclude", {}),
        "zigbee2mqtt_group": user_input.get("zigbee2mqtt_group", "").strip(),
    }


def _description_field(current: dict[str, Any]) -> tuple[Any, Any]:
    """Return the common description schema pair."""
    return (
        vol.Optional("description", default=current.get("description", "")),
        selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
    )


def _group_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the reusable light-group form."""
    current = defaults or {}
    name_key = (
        vol.Required("name", default=current["display_name"])
        if "display_name" in current
        else vol.Required("name")
    )
    description_key, description_selector = _description_field(current)
    return vol.Schema(
        {
            name_key: selector.TextSelector(),
            description_key: description_selector,
            vol.Required(
                "targets", default=current.get("targets", {})
            ): _target_selector(),
            vol.Optional(
                "exclude", default=current.get("exclude", {})
            ): _target_selector(),
            vol.Optional(
                "zigbee2mqtt_group",
                default=current.get("zigbee2mqtt_group", ""),
            ): selector.TextSelector(),
        }
    )


def _notification_identity_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the first notification step: meaning and activation behavior."""
    current = defaults or {}
    name_key = (
        vol.Required("name", default=current["display_name"])
        if "display_name" in current
        else vol.Required("name")
    )
    description_key, description_selector = _description_field(current)
    return vol.Schema(
        {
            name_key: selector.TextSelector(),
            description_key: description_selector,
            vol.Required(
                "activation", default=_activation_for_config(current)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=ACTIVATION_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _source_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the source-entity step for automatic rules."""
    current = defaults or {}
    source_key = (
        vol.Required("state_entity", default=current["state_entity"])
        if current.get("state_entity")
        else vol.Required("state_entity")
    )
    return vol.Schema({source_key: selector.EntitySelector()})


def _source_property_options(hass, entity_id: str) -> list:
    """List the entity state and its current attributes in plain language."""
    state = hass.states.get(entity_id) if hass is not None else None
    state_value = state.state if state is not None else "unknown"
    options = [
        selector.SelectOptionDict(
            value=SOURCE_STATE,
            label=f"Entity state (currently: {state_value})",
        )
    ]
    if state is None:
        return options
    for attribute, value in sorted(state.attributes.items()):
        if attribute in {"friendly_name", "icon"}:
            continue
        rendered = str(value)
        if len(rendered) > 60:
            rendered = f"{rendered[:57]}..."
        options.append(
            selector.SelectOptionDict(
                value=attribute,
                label=f"Attribute: {attribute} (currently: {rendered})",
            )
        )
    return options


def _notification_property_schema(hass, draft: dict[str, Any]) -> vol.Schema:
    """Choose whether a rule watches entity state or one attribute."""
    current = draft.get("state_attribute") or SOURCE_STATE
    return vol.Schema(
        {
            vol.Required("source_property", default=current): (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_source_property_options(hass, draft["state_entity"]),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        }
    )


def _state_options(
    hass,
    entity_id: str,
    attribute: str | None,
    selected: str | None,
) -> list[str]:
    """Return discoverable source states, retaining any previously saved one."""
    values: list[str] = []
    state = hass.states.get(entity_id) if hass is not None else None
    if state is not None:
        if attribute:
            current = state.attributes.get(attribute)
            if current is not None and not isinstance(current, (dict, list, tuple)):
                values.append(str(current))
        else:
            values.extend(
                str(value) for value in (state.attributes.get("options", []) or [])
            )
            if state.state not in {"unknown", "unavailable"}:
                values.append(state.state)
    if selected:
        values.append(selected)
    return list(dict.fromkeys(values))


def _notification_details_schema(
    hass,
    groups: dict[str, Any],
    draft: dict[str, Any],
) -> vol.Schema:
    """Build the routing and appearance step for a notification rule."""
    activation = Activation(draft["activation"])
    fields: dict[Any, Any] = {}

    if groups:
        fields[vol.Optional("groups", default=draft.get("groups", []))] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_slug_options(groups),
                    multiple=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        )

    fields.update(
        {
            vol.Optional(
                "targets", default=draft.get("targets", {})
            ): _target_selector(),
            vol.Optional(
                "exclude", default=draft.get("exclude", {})
            ): _target_selector(),
            vol.Required(
                "color", default=draft.get("color", "blue")
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=COLOR_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "effect", default=draft.get("effect", Effect.SOLID)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=EFFECT_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "effect_speed", default=draft.get("effect_speed", DEFAULT_SPEED)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=SPEED_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                "brightness", default=draft.get("brightness", DEFAULT_BRIGHTNESS)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                "priority", default=draft.get("priority", DEFAULT_PRIORITY)
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0,
                    max=100,
                    step=1,
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                "display_mode", default=draft.get("display_mode", DisplayMode.FULL)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=DISPLAY_MODE_OPTIONS,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )

    if activation in {Activation.STATE_WHILE, Activation.STATE_ENTERED}:
        state_values = _state_options(
            hass,
            draft["state_entity"],
            draft.get("state_attribute"),
            draft.get("active_state"),
        )
        default_state = draft.get("active_state") or (
            state_values[0] if state_values else "on"
        )
        fields[vol.Required("active_state", default=default_state)] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=state_values,
                    custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        )

    if activation in {Activation.STATE_ENTERED, Activation.MANUAL_TIMED}:
        fields[
            vol.Required("duration", default=max(1, int(draft.get("duration", 300))))
        ] = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=86400,
                step=1,
                unit_of_measurement="seconds",
            )
        )

    return vol.Schema(fields)


class NotifyLightsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create one notification catalog."""

    VERSION = 3

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
            options={"groups": {}, "notifications": {}},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> NotifyLightsOptionsFlow:
        # Home Assistant injects config_entry into OptionsFlow. Passing it to
        # the constructor is the obsolete API and breaks on current HA.
        return NotifyLightsOptionsFlow()


class NotifyLightsOptionsFlow(OptionsFlow):
    """Manage reusable target groups and notification rules."""

    def _options(self) -> dict[str, Any]:
        return self.config_entry.options

    def _save(self, *, groups=None, notifications=None):
        options = deepcopy(dict(self._options()))
        if groups is not None:
            options["groups"] = groups
        if notifications is not None:
            options["notifications"] = notifications
        return self.async_create_entry(data=options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        groups = self._options().get("groups", {})
        notifications = self._options().get("notifications", {})
        menu = ["add_group"]
        if groups:
            menu.extend(["modify_group", "delete_group"])
        menu.append("add_notification")
        if notifications:
            menu.extend(["modify_notification", "delete_notification"])
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_add_group(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input["name"]
            slug = _slugify(name)
            groups = dict(self._options().get("groups", {}))
            if not slug:
                errors["name"] = "invalid_name"
            elif slug in groups:
                errors["name"] = "name_exists"
            else:
                groups[slug] = _group_config(slug, user_input)
                _LOGGER.info("Added light group %r (slug=%r)", name, slug)
                return self._save(groups=groups)

        return self.async_show_form(
            step_id="add_group",
            data_schema=_group_schema(),
            errors=errors,
        )

    async def async_step_modify_group(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        groups = dict(self._options().get("groups", {}))
        if user_input is not None:
            self._editing_slug = user_input["slug"]
            return await self.async_step_modify_group_form()
        return self.async_show_form(
            step_id="modify_group",
            data_schema=_choose_schema(groups),
        )

    async def async_step_modify_group_form(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        slug = self._editing_slug
        groups = dict(self._options().get("groups", {}))
        if user_input is not None:
            groups[slug] = _group_config(slug, user_input)
            _LOGGER.info("Modified light group slug=%r", slug)
            return self._save(groups=groups)
        return self.async_show_form(
            step_id="modify_group_form",
            data_schema=_group_schema(groups[slug]),
        )

    async def async_step_delete_group(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        groups = dict(self._options().get("groups", {}))
        errors: dict[str, str] = {}
        if user_input is not None:
            slug = user_input["slug"]
            in_use = any(
                slug in config.get("groups", [])
                for config in self._options().get("notifications", {}).values()
            )
            if in_use:
                errors["base"] = "group_in_use"
            else:
                groups.pop(slug, None)
                _LOGGER.info("Deleted light group slug=%r", slug)
                return self._save(groups=groups)
        return self.async_show_form(
            step_id="delete_group",
            data_schema=_choose_schema(groups),
            errors=errors,
        )

    async def async_step_add_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            slug = _slugify(user_input["name"])
            if not slug:
                errors["name"] = "invalid_name"
            elif slug in self._options().get("notifications", {}):
                errors["name"] = "name_exists"
            else:
                self._editing_slug = slug
                self._draft = dict(user_input)
                return await self._next_notification_step()
        return self.async_show_form(
            step_id="add_notification",
            data_schema=_notification_identity_schema(),
            errors=errors,
        )

    async def async_step_modify_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = self._options().get("notifications", {})
        if user_input is not None:
            self._editing_slug = user_input["slug"]
            self._draft = dict(notifications[self._editing_slug])
            return await self.async_step_modify_notification_form()
        return self.async_show_form(
            step_id="modify_notification",
            data_schema=_choose_schema(notifications),
        )

    async def async_step_modify_notification_form(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            self._draft.update(user_input)
            return await self._next_notification_step()
        return self.async_show_form(
            step_id="modify_notification_form",
            data_schema=_notification_identity_schema(self._draft),
        )

    async def _next_notification_step(self) -> dict[str, Any]:
        activation = Activation(self._draft["activation"])
        if activation in {Activation.STATE_WHILE, Activation.STATE_ENTERED}:
            return await self.async_step_notification_source()
        return await self.async_step_notification_details()

    async def async_step_notification_source(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            self._draft.update(user_input)
            return await self.async_step_notification_property()
        return self.async_show_form(
            step_id="notification_source",
            data_schema=_source_schema(self._draft),
        )

    async def async_step_notification_property(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if user_input is not None:
            source_property = user_input["source_property"]
            self._draft["state_attribute"] = (
                None if source_property == SOURCE_STATE else source_property
            )
            return await self.async_step_notification_details()
        return self.async_show_form(
            step_id="notification_property",
            data_schema=_notification_property_schema(self.hass, self._draft),
        )

    async def async_step_notification_details(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        groups = self._options().get("groups", {})
        errors: dict[str, str] = {}
        if user_input is not None:
            self._draft.update(user_input)
            if not self._draft.get("groups") and not _has_targets(
                self._draft.get("targets")
            ):
                errors["base"] = "target_required"
            else:
                notifications = dict(self._options().get("notifications", {}))
                notifications[self._editing_slug] = notification_config(
                    self._editing_slug, self._draft
                )
                _LOGGER.info("Saved notification rule slug=%r", self._editing_slug)
                return self._save(notifications=notifications)
        return self.async_show_form(
            step_id="notification_details",
            data_schema=_notification_details_schema(self.hass, groups, self._draft),
            errors=errors,
        )

    async def async_step_delete_notification(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        notifications = dict(self._options().get("notifications", {}))
        if user_input is not None:
            slug = user_input["slug"]
            notifications.pop(slug, None)
            _LOGGER.info("Deleted notification rule slug=%r", slug)
            return self._save(notifications=notifications)
        return self.async_show_form(
            step_id="delete_notification",
            data_schema=_choose_schema(notifications),
        )


def _slug_options(records: dict[str, Any]) -> list:
    """Dropdown options listing records by display name."""
    return [
        selector.SelectOptionDict(value=slug, label=config["display_name"])
        for slug, config in records.items()
    ]


def _choose_schema(records: dict[str, Any]) -> vol.Schema:
    """Build a record chooser for edit/delete steps."""
    return vol.Schema(
        {
            vol.Required("slug"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=_slug_options(records),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            )
        }
    )


def _has_targets(targets: Any) -> bool:
    """Return whether a TargetSelector value contains any selection."""
    if isinstance(targets, list):
        return bool(targets)
    return bool(targets) and any(targets.values())
