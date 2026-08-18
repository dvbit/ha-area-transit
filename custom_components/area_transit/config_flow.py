"""Config, options and gate subentry flows for the Area Transit integration.

Structure (SPEC 1):

* one hub config entry, holding the global inter-gate window;
* one `gate` subentry per monitored gate, each one creating its own device.

Adding, editing or removing a gate updates the hub entry, which fires the
update listener registered in `__init__.py` and reloads the integration.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_AREA_IN,
    CONF_AREA_OUT,
    CONF_COOLDOWN,
    CONF_INTER_GATE_WINDOW,
    CONF_SENSOR_BOUNDARY,
    CONF_SENSOR_IN,
    CONF_SENSOR_OUT,
    CONF_SEQUENCE_TIMEOUT,
    DEFAULT_COOLDOWN,
    DEFAULT_INTER_GATE_WINDOW,
    DEFAULT_SEQUENCE_TIMEOUT,
    DOMAIN,
    MAX_COOLDOWN,
    MAX_INTER_GATE_WINDOW,
    MAX_SEQUENCE_TIMEOUT,
    MIN_COOLDOWN,
    MIN_INTER_GATE_WINDOW,
    MIN_SEQUENCE_TIMEOUT,
    SUBENTRY_TYPE_GATE,
)

#: Title of the single hub entry; the user renames it from the UI if needed.
DEFAULT_TITLE = "Area Transit"

#: Only binary sensors can drive a sequence (SPEC 2).
_BINARY_SENSOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain="binary_sensor")
)
_AREA = selector.AreaSelector(selector.AreaSelectorConfig())


def _seconds(minimum: float, maximum: float) -> selector.NumberSelector:
    """Return a bounded selector expressed in seconds."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="s",
        )
    )


#: Global settings, shared by every gate (SPEC 3).
HUB_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_INTER_GATE_WINDOW, default=DEFAULT_INTER_GATE_WINDOW
        ): _seconds(MIN_INTER_GATE_WINDOW, MAX_INTER_GATE_WINDOW),
    }
)

#: Per-gate settings (SPEC 1 and 2).
GATE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): selector.TextSelector(),
        vol.Required(CONF_AREA_IN): _AREA,
        vol.Required(CONF_AREA_OUT): _AREA,
        vol.Required(CONF_SENSOR_IN): _BINARY_SENSOR,
        vol.Required(CONF_SENSOR_OUT): _BINARY_SENSOR,
        # Optional, but mandatory inside the sequence once configured (SPEC 2).
        vol.Optional(CONF_SENSOR_BOUNDARY): _BINARY_SENSOR,
        vol.Required(CONF_SEQUENCE_TIMEOUT, default=DEFAULT_SEQUENCE_TIMEOUT): _seconds(
            MIN_SEQUENCE_TIMEOUT, MAX_SEQUENCE_TIMEOUT
        ),
        vol.Required(CONF_COOLDOWN, default=DEFAULT_COOLDOWN): _seconds(
            MIN_COOLDOWN, MAX_COOLDOWN
        ),
    }
)


def _validate_gate(user_input: dict[str, Any]) -> dict[str, str]:
    """Return the form errors of a gate configuration, empty when valid."""
    errors: dict[str, str] = {}

    if user_input[CONF_AREA_IN] == user_input[CONF_AREA_OUT]:
        errors[CONF_AREA_OUT] = "same_area"

    sensors = [user_input[CONF_SENSOR_IN], user_input[CONF_SENSOR_OUT]]
    if boundary := user_input.get(CONF_SENSOR_BOUNDARY):
        sensors.append(boundary)
    if len(set(sensors)) != len(sensors):
        errors["base"] = "duplicate_sensor"

    return errors


def _normalise_gate(user_input: dict[str, Any]) -> dict[str, Any]:
    """Coerce the numeric selector output to floats and drop empty values."""
    data = dict(user_input)
    data[CONF_SEQUENCE_TIMEOUT] = float(data[CONF_SEQUENCE_TIMEOUT])
    data[CONF_COOLDOWN] = float(data[CONF_COOLDOWN])
    if not data.get(CONF_SENSOR_BOUNDARY):
        data.pop(CONF_SENSOR_BOUNDARY, None)
    return data


class AreaTransitConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the creation of the single hub entry."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the hub entry; gates are added afterwards as subentries."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=HUB_SCHEMA)

        return self.async_create_entry(
            title=DEFAULT_TITLE,
            data={},
            options={CONF_INTER_GATE_WINDOW: float(user_input[CONF_INTER_GATE_WINDOW])},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handling the global settings."""
        return AreaTransitOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Declare the `gate` subentry type (SPEC 1)."""
        return {SUBENTRY_TYPE_GATE: GateSubentryFlowHandler}


class AreaTransitOptionsFlow(OptionsFlow):
    """Edit the global settings of the hub entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and store the inter-gate window."""
        if user_input is not None:
            return self.async_create_entry(
                data={CONF_INTER_GATE_WINDOW: float(user_input[CONF_INTER_GATE_WINDOW])}
            )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                HUB_SCHEMA, self.config_entry.options
            ),
        )


class GateSubentryFlowHandler(ConfigSubentryFlow):
    """Create and reconfigure a gate."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a new gate to the hub entry."""
        errors: dict[str, str] = {}

        if user_input is not None and not (errors := _validate_gate(user_input)):
            data = _normalise_gate(user_input)
            return self.async_create_entry(title=data[CONF_NAME], data=data)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                GATE_SCHEMA, user_input or {}
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Edit an existing gate.

        `async_update_and_abort` is used on purpose: the hub entry registers an
        update listener, and `async_update_reload_and_abort` refuses to run in
        that case. The listener performs the reload.
        """
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None and not (errors := _validate_gate(user_input)):
            data = _normalise_gate(user_input)
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=data[CONF_NAME],
                data=data,
            )

        suggested: Mapping[str, Any] = user_input or subentry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(GATE_SCHEMA, suggested),
            errors=errors,
        )
