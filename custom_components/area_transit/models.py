"""Data models for the Area Transit integration.

All runtime objects exchanged between the gate state machines (`gate.py`),
the chain detector (`chain.py`), the manager (`coordinator.py`) and the
entities (`sensor.py`) are defined here, so the contract stays in one place.

Reference: SPEC.md sections 2 (detection) and 3 (gate chaining).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_NAME

from .const import (
    ATTR_DESTINATION,
    ATTR_DESTINATION_ID,
    ATTR_DIRECTION,
    ATTR_DURATION,
    ATTR_ENDED,
    ATTR_FROM_AREA,
    ATTR_FROM_AREA_ID,
    ATTR_GATE_ID,
    ATTR_GATE_NAME,
    ATTR_GATES,
    ATTR_ORIGIN,
    ATTR_ORIGIN_ID,
    ATTR_SENSORS,
    ATTR_STARTED,
    ATTR_TO_AREA,
    ATTR_TO_AREA_ID,
    ATTR_TRANSITS,
    ATTR_VIA,
    ATTR_VIA_IDS,
    CONF_AREA_IN,
    CONF_AREA_OUT,
    CONF_COOLDOWN,
    CONF_SENSOR_BOUNDARY,
    CONF_SENSOR_IN,
    CONF_SENSOR_OUT,
    CONF_SEQUENCE_TIMEOUT,
    DEFAULT_COOLDOWN,
    DEFAULT_SEQUENCE_TIMEOUT,
    DIRECTION_IN_TO_OUT,
)


@dataclass(frozen=True, slots=True)
class GateConfig:
    """Immutable configuration of a single gate (SPEC 1).

    A gate connects exactly two areas and owns two mandatory motion sensors
    (one per area) plus an optional boundary sensor. When the boundary sensor
    is configured it becomes MANDATORY inside the sequence (SPEC 2).
    """

    gate_id: str
    """Stable identifier: the subentry_id assigned by Home Assistant."""

    name: str
    area_in: str
    """Area registry id of the "in" side of the gate."""

    area_out: str
    """Area registry id of the "out" side of the gate."""

    sensor_in: str
    sensor_out: str
    sensor_boundary: str | None
    sequence_timeout: float
    cooldown: float

    @classmethod
    def from_subentry(cls, subentry: ConfigSubentry) -> GateConfig:
        """Build a GateConfig from its persisted subentry."""
        data = subentry.data
        return cls(
            gate_id=subentry.subentry_id,
            name=data.get(CONF_NAME) or subentry.title,
            area_in=data[CONF_AREA_IN],
            area_out=data[CONF_AREA_OUT],
            sensor_in=data[CONF_SENSOR_IN],
            sensor_out=data[CONF_SENSOR_OUT],
            sensor_boundary=data.get(CONF_SENSOR_BOUNDARY) or None,
            sequence_timeout=float(
                data.get(CONF_SEQUENCE_TIMEOUT, DEFAULT_SEQUENCE_TIMEOUT)
            ),
            cooldown=float(data.get(CONF_COOLDOWN, DEFAULT_COOLDOWN)),
        )

    @property
    def tracked_entities(self) -> list[str]:
        """Return every entity the gate has to listen to."""
        entities = [self.sensor_in, self.sensor_out]
        if self.sensor_boundary:
            entities.append(self.sensor_boundary)
        return entities

    def expected_sequence(self, direction: str) -> list[str]:
        """Return the ordered entity ids required for `direction` (SPEC 2).

        With a boundary sensor configured the sequence is strictly
        `start area -> boundary -> destination area`; without it the boundary
        step is simply absent.
        """
        if direction == DIRECTION_IN_TO_OUT:
            sequence = [self.sensor_in, self.sensor_out]
        else:
            sequence = [self.sensor_out, self.sensor_in]
        if self.sensor_boundary:
            sequence.insert(1, self.sensor_boundary)
        return sequence

    def areas_for(self, direction: str) -> tuple[str, str]:
        """Return the (from_area, to_area) pair for `direction`."""
        if direction == DIRECTION_IN_TO_OUT:
            return self.area_in, self.area_out
        return self.area_out, self.area_in


@dataclass(frozen=True, slots=True)
class TransitRecord:
    """A validated single-gate transit (SPEC 2)."""

    gate_id: str
    gate_name: str
    direction: str
    from_area: str
    """Area registry id the person came from."""

    to_area: str
    """Area registry id the person moved into."""

    from_area_name: str
    to_area_name: str
    started: datetime
    ended: datetime
    duration: float
    sensors: list[str]
    boundary_used: bool

    def as_event_data(self) -> dict[str, Any]:
        """Serialise the record for the `area_transit_transit` bus event."""
        return {
            ATTR_GATE_ID: self.gate_id,
            ATTR_GATE_NAME: self.gate_name,
            ATTR_DIRECTION: self.direction,
            ATTR_FROM_AREA_ID: self.from_area,
            ATTR_FROM_AREA: self.from_area_name,
            ATTR_TO_AREA_ID: self.to_area,
            ATTR_TO_AREA: self.to_area_name,
            ATTR_STARTED: self.started.isoformat(),
            ATTR_ENDED: self.ended.isoformat(),
            ATTR_DURATION: round(self.duration, 3),
            ATTR_SENSORS: list(self.sensors),
            "boundary_used": self.boundary_used,
        }


@dataclass(slots=True)
class PathRecord:
    """A multi-gate path built from contiguous transits (SPEC 3).

    A path is created when two transits share an area (the destination of the
    first is the origin of the second) and happen within the configured
    inter-gate window. It keeps growing while further contiguous transits
    arrive in time, and is emitted once the window expires.
    """

    transits: list[TransitRecord] = field(default_factory=list)

    @property
    def origin(self) -> str:
        """Area id the path starts from."""
        return self.transits[0].from_area

    @property
    def origin_name(self) -> str:
        """Area name the path starts from."""
        return self.transits[0].from_area_name

    @property
    def destination(self) -> str:
        """Area id the path currently ends in."""
        return self.transits[-1].to_area

    @property
    def destination_name(self) -> str:
        """Area name the path currently ends in."""
        return self.transits[-1].to_area_name

    @property
    def via(self) -> list[str]:
        """Area ids crossed between origin and destination."""
        return [transit.to_area for transit in self.transits[:-1]]

    @property
    def via_names(self) -> list[str]:
        """Area names crossed between origin and destination."""
        return [transit.to_area_name for transit in self.transits[:-1]]

    @property
    def visited_areas(self) -> list[str]:
        """Every area id touched by the path, origin included."""
        return [self.origin, *(transit.to_area for transit in self.transits)]

    @property
    def duration(self) -> float:
        """Total duration, from the first sensor to the last one."""
        return (self.transits[-1].ended - self.transits[0].started).total_seconds()

    def as_event_data(self) -> dict[str, Any]:
        """Serialise the record for the `area_transit_path` bus event."""
        return {
            ATTR_ORIGIN_ID: self.origin,
            ATTR_ORIGIN: self.origin_name,
            ATTR_DESTINATION_ID: self.destination,
            ATTR_DESTINATION: self.destination_name,
            ATTR_VIA_IDS: self.via,
            ATTR_VIA: self.via_names,
            ATTR_GATES: [transit.gate_name for transit in self.transits],
            ATTR_STARTED: self.transits[0].started.isoformat(),
            ATTR_ENDED: self.transits[-1].ended.isoformat(),
            ATTR_DURATION: round(self.duration, 3),
            ATTR_TRANSITS: [transit.as_event_data() for transit in self.transits],
        }
