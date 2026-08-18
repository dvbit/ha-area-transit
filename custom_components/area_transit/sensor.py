"""Sensor platform for the Area Transit integration.

Entities created (SPEC 4):

per gate (device = the gate, owned by its subentry)
    sensor.<gate>_last_transit         timestamp of the last validated transit
    sensor.<gate>_direction            direction of the last validated transit
    sensor.<gate>_transits_in_to_out   counter, area_in -> area_out
    sensor.<gate>_transits_out_to_in   counter, area_out -> area_in

per monitored area (device = the area)
    sensor.<area>_occupancy            estimated people count, never negative

on the single hub device (one per config entry)
    sensor.area_transit_hub_last_path       timestamp of the last completed path
    sensor.area_transit_hub_total_transits  transits across every gate

Every entity restores its value after a Home Assistant restart (SPEC 4), and
exposes the reset services described in SPEC 5.
"""

from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_BOUNDARY_USED,
    ATTR_DESTINATION,
    ATTR_DESTINATION_ID,
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_FROM_AREA,
    ATTR_FROM_AREA_ID,
    ATTR_GATE_NAME,
    ATTR_GATES,
    ATTR_ORIGIN,
    ATTR_ORIGIN_ID,
    ATTR_SENSORS,
    ATTR_STARTED,
    ATTR_TO_AREA,
    ATTR_TO_AREA_ID,
    ATTR_VALUE,
    ATTR_VIA,
    ATTR_VIA_IDS,
    DIRECTION_IN_TO_OUT,
    DIRECTION_OUT_TO_IN,
    DIRECTIONS,
    DOMAIN,
    HUB_DEVICE_NAME,
    KEY_COUNT_IN_TO_OUT,
    KEY_COUNT_OUT_TO_IN,
    KEY_DIRECTION,
    KEY_LAST_PATH,
    KEY_LAST_TRANSIT,
    KEY_OCCUPANCY,
    KEY_TOTAL_TRANSITS,
    MANUFACTURER,
    MODEL_AREA,
    MODEL_GATE,
    MODEL_HUB,
    SERVICE_RESET_COUNTERS,
    SERVICE_RESET_OCCUPANCY,
)
from .coordinator import AreaTransitConfigEntry, AreaTransitManager
from .models import GateConfig, PathRecord, TransitRecord

_LOGGER = logging.getLogger(__name__)

#: Upper bound accepted by `reset_occupancy`, high enough for any real home.
MAX_OCCUPANCY = 1000


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AreaTransitConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the gate entities and the per-area occupancy sensors."""
    manager = entry.runtime_data

    for config in manager.gate_configs:
        # Entities are attached to their own subentry so removing the gate
        # removes its device and entities (SPEC 1).
        async_add_entities(
            [
                GateLastTransitSensor(manager, config),
                GateDirectionSensor(manager, config),
                GateCounterSensor(manager, config, DIRECTION_IN_TO_OUT),
                GateCounterSensor(manager, config, DIRECTION_OUT_TO_IN),
            ],
            config_subentry_id=config.gate_id,
        )

    async_add_entities(
        AreaOccupancySensor(manager, area_id) for area_id in manager.monitored_areas
    )

    # Hub summary entities (SPEC 4): one device aggregating cross-gate totals.
    async_add_entities([HubLastPathSensor(manager), HubTotalTransitsSensor(manager)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_RESET_OCCUPANCY,
        {
            vol.Optional(ATTR_VALUE, default=0): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=MAX_OCCUPANCY)
            )
        },
        "async_reset_occupancy",
    )
    platform.async_register_entity_service(
        SERVICE_RESET_COUNTERS, None, "async_reset_counters"
    )


class AreaTransitSensor(RestoreSensor):
    """Common behaviour of every Area Transit sensor."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    async def async_reset_occupancy(self, value: int) -> None:
        """Handle `area_transit.reset_occupancy` (overridden where relevant)."""
        _LOGGER.debug(
            "%s ignores reset_occupancy, not an occupancy sensor", self.entity_id
        )

    async def async_reset_counters(self) -> None:
        """Handle `area_transit.reset_counters` (overridden where relevant)."""
        _LOGGER.debug("%s ignores reset_counters, nothing to reset", self.entity_id)


class GateSensor(AreaTransitSensor):
    """Base class of the four entities describing a gate."""

    def __init__(
        self, manager: AreaTransitManager, config: GateConfig, key: str
    ) -> None:
        """Attach the entity to the device representing the gate."""
        self._manager = manager
        self._gate = config
        self._attr_translation_key = key
        self._attr_unique_id = f"{config.gate_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config.gate_id)},
            name=config.name,
            manufacturer=MANUFACTURER,
            model=MODEL_GATE,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        """Restore the previous value and subscribe to the gate transits."""
        await super().async_added_to_hass()
        await self._async_restore()
        self.async_on_remove(
            self._manager.async_add_transit_listener(
                self._gate.gate_id, self._handle_transit
            )
        )

    async def _async_restore(self) -> None:
        """Restore the entity value after a restart (SPEC 4)."""

    @callback
    def _handle_transit(self, record: TransitRecord) -> None:
        """React to a validated transit on this gate."""
        raise NotImplementedError


class GateLastTransitSensor(GateSensor):
    """Timestamp and details of the last transit through the gate."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager: AreaTransitManager, config: GateConfig) -> None:
        """Initialise without any known transit."""
        super().__init__(manager, config, KEY_LAST_TRANSIT)
        self._attr_native_value: datetime | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def _async_restore(self) -> None:
        """Restore both the timestamp and the attributes of the last transit."""
        if (last_state := await self.async_get_last_state()) is None:
            return
        if (restored := dt_util.parse_datetime(last_state.state)) is not None:
            self._attr_native_value = restored
            # Attributes are not covered by RestoreSensor, copy the ones we own.
            self._attr_extra_state_attributes = {
                key: value
                for key, value in last_state.attributes.items()
                if key
                in (
                    ATTR_DIRECTION,
                    ATTR_FROM_AREA,
                    ATTR_FROM_AREA_ID,
                    ATTR_TO_AREA,
                    ATTR_TO_AREA_ID,
                    ATTR_DURATION,
                    ATTR_SENSORS,
                    ATTR_STARTED,
                    ATTR_BOUNDARY_USED,
                    ATTR_GATE_NAME,
                )
            }
            _LOGGER.debug("%s restored to %s", self.entity_id, restored)

    @callback
    def _handle_transit(self, record: TransitRecord) -> None:
        """Publish the new transit."""
        self._attr_native_value = record.ended
        self._attr_extra_state_attributes = {
            ATTR_GATE_NAME: record.gate_name,
            ATTR_DIRECTION: record.direction,
            ATTR_FROM_AREA: record.from_area_name,
            ATTR_FROM_AREA_ID: record.from_area,
            ATTR_TO_AREA: record.to_area_name,
            ATTR_TO_AREA_ID: record.to_area,
            ATTR_STARTED: record.started.isoformat(),
            ATTR_DURATION: round(record.duration, 3),
            ATTR_SENSORS: list(record.sensors),
            ATTR_BOUNDARY_USED: record.boundary_used,
        }
        self.async_write_ha_state()

    async def async_reset_counters(self) -> None:
        """Clear the last transit together with the counters of the gate."""
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()
        _LOGGER.info("Last transit cleared on %s", self.entity_id)


class GateDirectionSensor(GateSensor):
    """Direction of the last transit through the gate."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = DIRECTIONS

    def __init__(self, manager: AreaTransitManager, config: GateConfig) -> None:
        """Initialise without any known direction."""
        super().__init__(manager, config, KEY_DIRECTION)
        self._attr_native_value: str | None = None

    async def _async_restore(self) -> None:
        """Restore the last known direction, ignoring unknown/unavailable."""
        if (last_state := await self.async_get_last_state()) is None:
            return
        if last_state.state in DIRECTIONS:
            self._attr_native_value = last_state.state
            _LOGGER.debug("%s restored to %s", self.entity_id, last_state.state)

    @callback
    def _handle_transit(self, record: TransitRecord) -> None:
        """Publish the direction of the new transit."""
        self._attr_native_value = record.direction
        self.async_write_ha_state()

    async def async_reset_counters(self) -> None:
        """Clear the direction together with the counters of the gate."""
        self._attr_native_value = None
        self.async_write_ha_state()


class GateCounterSensor(GateSensor):
    """Number of transits registered on the gate in one direction."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, manager: AreaTransitManager, config: GateConfig, direction: str
    ) -> None:
        """Initialise the counter dedicated to `direction`."""
        key = (
            KEY_COUNT_IN_TO_OUT
            if direction == DIRECTION_IN_TO_OUT
            else KEY_COUNT_OUT_TO_IN
        )
        super().__init__(manager, config, key)
        self._direction = direction
        self._attr_native_value: int = 0

    async def _async_restore(self) -> None:
        """Restore the counter, starting from zero when nothing is stored."""
        if (data := await self.async_get_last_sensor_data()) is None:
            return
        try:
            self._attr_native_value = int(data.native_value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            _LOGGER.debug(
                "%s had no usable stored value (%s), restarting from 0",
                self.entity_id,
                data.native_value,
            )
            return
        _LOGGER.debug("%s restored to %d", self.entity_id, self._attr_native_value)

    @callback
    def _handle_transit(self, record: TransitRecord) -> None:
        """Increment the counter when the transit matches its direction."""
        if record.direction != self._direction:
            return
        self._attr_native_value += 1
        self.async_write_ha_state()

    async def async_reset_counters(self) -> None:
        """Handle `area_transit.reset_counters` (SPEC 5)."""
        self._attr_native_value = 0
        self.async_write_ha_state()
        _LOGGER.info("Counter %s reset to 0", self.entity_id)


class AreaOccupancySensor(AreaTransitSensor):
    """Estimated number of people currently in an area (SPEC 4).

    The value is a running total fed by the transits: it is an estimate, it is
    clamped to zero and it can be realigned at any time with
    `area_transit.reset_occupancy` (SPEC 5).
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = KEY_OCCUPANCY

    def __init__(self, manager: AreaTransitManager, area_id: str) -> None:
        """Attach the entity to the device representing the area."""
        self._manager = manager
        self._area_id = area_id
        area_name = manager.area_name(area_id)
        self._attr_unique_id = f"{manager.entry.entry_id}_occupancy_{area_id}"
        self._attr_native_value: int = 0
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"area_{area_id}")},
            name=area_name,
            manufacturer=MANUFACTURER,
            model=MODEL_AREA,
            entry_type=DeviceEntryType.SERVICE,
            suggested_area=area_name,
        )

    async def async_added_to_hass(self) -> None:
        """Restore the previous count and subscribe to the area deltas."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            try:
                self._attr_native_value = max(0, int(data.native_value))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "%s had no usable stored value (%s), restarting from 0",
                    self.entity_id,
                    data.native_value,
                )
            else:
                _LOGGER.debug(
                    "%s restored to %d", self.entity_id, self._attr_native_value
                )

        self.async_on_remove(
            self._manager.async_add_occupancy_listener(
                self._area_id, self._handle_delta
            )
        )

    @callback
    def _handle_delta(self, delta: int) -> None:
        """Apply an occupancy delta, never going below zero."""
        new_value = max(0, self._attr_native_value + delta)
        if new_value == self._attr_native_value and delta < 0:
            _LOGGER.debug(
                "%s already at 0, negative delta ignored (clamp)", self.entity_id
            )
        self._attr_native_value = new_value
        self.async_write_ha_state()

    async def async_reset_occupancy(self, value: int) -> None:
        """Handle `area_transit.reset_occupancy` (SPEC 5)."""
        self._attr_native_value = max(0, value)
        self.async_write_ha_state()
        _LOGGER.info(
            "Occupancy of %s set to %d", self.entity_id, self._attr_native_value
        )


class HubSensor(AreaTransitSensor):
    """Base class of the summary entities attached to the single hub device.

    Unlike gate and area entities, these are not tied to a subentry or to a
    single monitored area: they aggregate activity across every gate (SPEC 4).
    """

    def __init__(self, manager: AreaTransitManager, key: str) -> None:
        """Attach the entity to the hub device, identified by the entry id."""
        self._manager = manager
        self._attr_translation_key = key
        self._attr_unique_id = f"{manager.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name=HUB_DEVICE_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL_HUB,
            entry_type=DeviceEntryType.SERVICE,
        )


class HubLastPathSensor(HubSensor):
    """Timestamp and details of the last completed multi-gate path (SPEC 3, 4).

    A path only exists as the `area_transit_path` bus event until now; this
    entity is the first place it is also exposed as state.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, manager: AreaTransitManager) -> None:
        """Initialise without any known path."""
        super().__init__(manager, KEY_LAST_PATH)
        self._attr_native_value: datetime | None = None
        self._attr_extra_state_attributes: dict[str, Any] = {}

    async def async_added_to_hass(self) -> None:
        """Restore the previous path and subscribe to newly completed ones."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None and (
            restored := dt_util.parse_datetime(last_state.state)
        ) is not None:
            self._attr_native_value = restored
            # Attributes are not covered by RestoreSensor, copy the ones we own.
            self._attr_extra_state_attributes = {
                key: value
                for key, value in last_state.attributes.items()
                if key
                in (
                    ATTR_ORIGIN,
                    ATTR_ORIGIN_ID,
                    ATTR_DESTINATION,
                    ATTR_DESTINATION_ID,
                    ATTR_VIA,
                    ATTR_VIA_IDS,
                    ATTR_GATES,
                    ATTR_STARTED,
                    ATTR_DURATION,
                )
            }
            _LOGGER.debug("%s restored to %s", self.entity_id, restored)

        self.async_on_remove(self._manager.async_add_path_listener(self._handle_path))

    @callback
    def _handle_path(self, record: PathRecord) -> None:
        """Publish the newly completed path."""
        self._attr_native_value = record.transits[-1].ended
        self._attr_extra_state_attributes = {
            ATTR_ORIGIN_ID: record.origin,
            ATTR_ORIGIN: record.origin_name,
            ATTR_DESTINATION_ID: record.destination,
            ATTR_DESTINATION: record.destination_name,
            ATTR_VIA_IDS: record.via,
            ATTR_VIA: record.via_names,
            ATTR_GATES: [transit.gate_name for transit in record.transits],
            ATTR_STARTED: record.transits[0].started.isoformat(),
            ATTR_DURATION: round(record.duration, 3),
        }
        self.async_write_ha_state()

    async def async_reset_counters(self) -> None:
        """Clear the last path together with the hub counters (SPEC 5)."""
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        self.async_write_ha_state()
        _LOGGER.info("Last path cleared on %s", self.entity_id)


class HubTotalTransitsSensor(HubSensor):
    """Total number of transits registered across every gate (SPEC 4)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, manager: AreaTransitManager) -> None:
        """Initialise the counter at zero."""
        super().__init__(manager, KEY_TOTAL_TRANSITS)
        self._attr_native_value: int = 0

    async def async_added_to_hass(self) -> None:
        """Restore the previous total and subscribe to every gate's transits."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) is not None:
            try:
                self._attr_native_value = int(data.native_value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "%s had no usable stored value (%s), restarting from 0",
                    self.entity_id,
                    data.native_value,
                )
            else:
                _LOGGER.debug(
                    "%s restored to %d", self.entity_id, self._attr_native_value
                )

        self.async_on_remove(
            self._manager.async_add_global_transit_listener(self._handle_transit)
        )

    @callback
    def _handle_transit(self, _record: TransitRecord) -> None:
        """Increment the counter for every transit, on any gate."""
        self._attr_native_value += 1
        self.async_write_ha_state()

    async def async_reset_counters(self) -> None:
        """Handle `area_transit.reset_counters` (SPEC 5) for the hub total."""
        self._attr_native_value = 0
        self.async_write_ha_state()
        _LOGGER.info("Counter %s reset to 0", self.entity_id)
