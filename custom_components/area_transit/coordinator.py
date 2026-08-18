"""Runtime manager for the Area Transit integration.

Owns one `GateTracker` per configured gate (SPEC 1), feeds every validated
transit to the `ChainDetector` (SPEC 3), fires the bus events (SPEC 6) and
notifies the entities (SPEC 4).

The manager deliberately keeps **no** counter or occupancy value: those live in
the entities, which restore them after a restart (SPEC 4). The manager only
publishes deltas.
"""

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar

from .chain import ChainDetector
from .const import (
    CONF_INTER_GATE_WINDOW,
    DEFAULT_INTER_GATE_WINDOW,
    EVENT_PATH,
    EVENT_TRANSIT,
    SUBENTRY_TYPE_GATE,
)
from .gate import GateTracker
from .models import GateConfig, PathRecord, TransitRecord

_LOGGER = logging.getLogger(__name__)

#: Notified with the transit that just happened on a specific gate.
type TransitListener = Callable[[TransitRecord], None]
#: Notified with the occupancy delta (+1 / -1) of a specific area.
type OccupancyListener = Callable[[int], None]
#: Notified with every validated transit, on any gate (hub totals, SPEC 4).
type GlobalTransitListener = Callable[[TransitRecord], None]
#: Notified with every completed multi-gate path (hub last path, SPEC 4).
type PathListener = Callable[[PathRecord], None]

#: Config entry carrying the manager in its runtime data.
type AreaTransitConfigEntry = ConfigEntry[AreaTransitManager]


class AreaTransitManager:
    """Glue between the gate state machines, the chain detector and the entities."""

    def __init__(self, hass: HomeAssistant, entry: AreaTransitConfigEntry) -> None:
        """Read the configuration without starting anything yet."""
        self.hass = hass
        self.entry = entry
        self._area_registry = ar.async_get(hass)

        self._gates: dict[str, GateTracker] = {}
        self._transit_listeners: dict[str, list[TransitListener]] = {}
        self._occupancy_listeners: dict[str, list[OccupancyListener]] = {}
        # Hub-wide listeners (SPEC 4): every transit / every completed path,
        # regardless of which gate produced it.
        self._global_transit_listeners: list[GlobalTransitListener] = []
        self._path_listeners: list[PathListener] = []

        window = float(
            entry.options.get(CONF_INTER_GATE_WINDOW, DEFAULT_INTER_GATE_WINDOW)
        )
        self._chain = ChainDetector(hass, window, self._handle_path)

    # -- configuration -------------------------------------------------------

    @property
    def gate_configs(self) -> list[GateConfig]:
        """Return the configuration of every gate, in subentry order."""
        return [tracker.config for tracker in self._gates.values()]

    @property
    def monitored_areas(self) -> list[str]:
        """Return every area id touched by at least one gate (SPEC 4)."""
        areas: list[str] = []
        for config in self.gate_configs:
            for area_id in (config.area_in, config.area_out):
                if area_id not in areas:
                    areas.append(area_id)
        return areas

    def area_name(self, area_id: str) -> str:
        """Return the registry name of an area, falling back to its id."""
        if (area := self._area_registry.async_get_area(area_id)) is not None:
            return area.name
        _LOGGER.warning("Area '%s' is not in the area registry any more", area_id)
        return area_id

    # -- lifecycle -----------------------------------------------------------

    @callback
    def async_setup(self) -> None:
        """Build one tracker per `gate` subentry, without subscribing yet.

        Trackers are armed later by `async_start`, once the entities exist and
        are able to receive the first transit.
        """
        for subentry in self.entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_GATE:
                continue
            try:
                config = GateConfig.from_subentry(subentry)
            except KeyError:
                _LOGGER.exception(
                    "Gate '%s' has an incomplete configuration and was skipped",
                    subentry.title,
                )
                continue

            self._gates[config.gate_id] = GateTracker(
                self.hass, config, self._handle_transit, self.area_name
            )

        _LOGGER.info(
            "Area Transit configured with %d gate(s) over %d area(s)",
            len(self._gates),
            len(self.monitored_areas),
        )

    @callback
    def async_start(self) -> None:
        """Arm every tracker; from now on transits are detected."""
        for tracker in self._gates.values():
            tracker.async_start()

    @callback
    def async_shutdown(self) -> None:
        """Stop every tracker and the chain detector."""
        for tracker in self._gates.values():
            tracker.async_stop()
        self._gates.clear()
        self._chain.async_stop()
        _LOGGER.debug("Area Transit manager shut down")

    # -- entity subscriptions ------------------------------------------------

    @callback
    def async_add_transit_listener(
        self, gate_id: str, listener: TransitListener
    ) -> CALLBACK_TYPE:
        """Subscribe an entity to the transits of one gate."""
        self._transit_listeners.setdefault(gate_id, []).append(listener)

        @callback
        def _unsubscribe() -> None:
            self._transit_listeners[gate_id].remove(listener)

        return _unsubscribe

    @callback
    def async_add_occupancy_listener(
        self, area_id: str, listener: OccupancyListener
    ) -> CALLBACK_TYPE:
        """Subscribe an entity to the occupancy deltas of one area."""
        self._occupancy_listeners.setdefault(area_id, []).append(listener)

        @callback
        def _unsubscribe() -> None:
            self._occupancy_listeners[area_id].remove(listener)

        return _unsubscribe

    @callback
    def async_add_global_transit_listener(
        self, listener: GlobalTransitListener
    ) -> CALLBACK_TYPE:
        """Subscribe the hub total-transits entity to every gate (SPEC 4)."""
        self._global_transit_listeners.append(listener)

        @callback
        def _unsubscribe() -> None:
            self._global_transit_listeners.remove(listener)

        return _unsubscribe

    @callback
    def async_add_path_listener(self, listener: PathListener) -> CALLBACK_TYPE:
        """Subscribe the hub last-path entity to every completed path (SPEC 4)."""
        self._path_listeners.append(listener)

        @callback
        def _unsubscribe() -> None:
            self._path_listeners.remove(listener)

        return _unsubscribe

    # -- event handling ------------------------------------------------------

    @callback
    def _handle_transit(self, record: TransitRecord) -> None:
        """Publish a validated transit to entities, bus and chain detector."""
        for listener in list(self._transit_listeners.get(record.gate_id, ())):
            listener(record)
        for listener in list(self._global_transit_listeners):
            listener(record)

        # Occupancy follows the movement: one person leaves, one arrives.
        self._notify_occupancy(record.from_area, -1)
        self._notify_occupancy(record.to_area, 1)

        self.hass.bus.async_fire(EVENT_TRANSIT, record.as_event_data())
        self._chain.async_add_transit(record)

    @callback
    def _handle_path(self, record: PathRecord) -> None:
        """Publish a completed multi-gate path on the bus (SPEC 3) and hub (SPEC 4)."""
        self.hass.bus.async_fire(EVENT_PATH, record.as_event_data())
        for listener in list(self._path_listeners):
            listener(record)

    @callback
    def _notify_occupancy(self, area_id: str, delta: int) -> None:
        """Forward an occupancy delta to the sensor of `area_id`."""
        listeners = self._occupancy_listeners.get(area_id)
        if not listeners:
            _LOGGER.debug("No occupancy sensor listening on area '%s'", area_id)
            return
        for listener in list(listeners):
            listener(delta)
