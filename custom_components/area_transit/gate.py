"""Single-gate sequence detection for the Area Transit integration.

Implements SPEC.md section 2: a transit is registered only when the sensors of
a gate switch to `on` in the exact expected order and the whole sequence
completes within `sequence_timeout` seconds.

    without boundary sensor:  Area X  ->  Area Y
    with boundary sensor:     Area X  ->  Boundary  ->  Area Y

Any other combination is discarded and logged, so a misconfigured gate is
visible in the Home Assistant log instead of silently producing garbage.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging

from homeassistant.const import STATE_ON
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import DIRECTION_IN_TO_OUT, DIRECTION_OUT_TO_IN
from .models import GateConfig, TransitRecord

_LOGGER = logging.getLogger(__name__)

#: Callback invoked by the tracker for every validated transit.
type TransitCallback = Callable[[TransitRecord], None]
#: Resolves an area registry id into a human readable name.
type AreaNameResolver = Callable[[str], str]


class GateTracker:
    """State machine watching the sensors of one gate."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: GateConfig,
        on_transit: TransitCallback,
        resolve_area_name: AreaNameResolver,
    ) -> None:
        """Initialise the tracker without subscribing to anything yet."""
        self._hass = hass
        self._config = config
        self._on_transit = on_transit
        self._resolve_area_name = resolve_area_name

        # Active sequence state; all reset together by `_reset_sequence`.
        self._direction: str | None = None
        self._progress: list[str] = []
        self._started: datetime | None = None
        self._timeout_unsub: CALLBACK_TYPE | None = None

        # Cooldown window closing the gate right after a registered transit.
        self._cooldown_until: datetime | None = None

        self._state_unsub: CALLBACK_TYPE | None = None

    @property
    def config(self) -> GateConfig:
        """Return the immutable configuration of the gate."""
        return self._config

    # -- lifecycle -----------------------------------------------------------

    @callback
    def async_start(self) -> None:
        """Subscribe to the state changes of every sensor of the gate."""
        self._state_unsub = async_track_state_change_event(
            self._hass, self._config.tracked_entities, self._async_state_changed
        )
        _LOGGER.debug(
            "Gate '%s' watching %s (timeout %.0fs, cooldown %.0fs, boundary %s)",
            self._config.name,
            self._config.tracked_entities,
            self._config.sequence_timeout,
            self._config.cooldown,
            self._config.sensor_boundary or "not configured",
        )

    @callback
    def async_stop(self) -> None:
        """Unsubscribe and drop any pending sequence."""
        if self._state_unsub is not None:
            self._state_unsub()
            self._state_unsub = None
        self._reset_sequence()
        _LOGGER.debug("Gate '%s' stopped", self._config.name)

    # -- event handling ------------------------------------------------------

    @callback
    def _async_state_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle an `off -> on` edge on one of the gate sensors."""
        new_state = event.data["new_state"]
        old_state = event.data["old_state"]

        # Only rising edges matter. `old_state is None` means the entity was
        # just added to the machine, which is not a real detection.
        if new_state is None or new_state.state != STATE_ON:
            return
        if old_state is None or old_state.state == STATE_ON:
            return

        entity_id = event.data["entity_id"]
        now = dt_util.utcnow()

        if self._cooldown_until is not None and now < self._cooldown_until:
            _LOGGER.debug(
                "Gate '%s': %s ignored, cooldown active for %.1fs more",
                self._config.name,
                entity_id,
                (self._cooldown_until - now).total_seconds(),
            )
            return

        if self._direction is None:
            self._start_sequence(entity_id, now)
            return

        self._advance_sequence(entity_id, now)

    @callback
    def _start_sequence(self, entity_id: str, now: datetime) -> None:
        """Open a new sequence, if the triggering sensor may start one."""
        if entity_id == self._config.sensor_in:
            direction = DIRECTION_IN_TO_OUT
        elif entity_id == self._config.sensor_out:
            direction = DIRECTION_OUT_TO_IN
        else:
            # The boundary sensor alone carries no direction (SPEC 2).
            _LOGGER.debug(
                "Gate '%s': boundary %s fired first, no sequence started",
                self._config.name,
                entity_id,
            )
            return

        self._direction = direction
        self._progress = [entity_id]
        self._started = now
        self._timeout_unsub = async_call_later(
            self._hass, self._config.sequence_timeout, self._async_sequence_timeout
        )
        _LOGGER.debug(
            "Gate '%s': sequence started by %s, direction %s, expecting %s",
            self._config.name,
            entity_id,
            direction,
            self._config.expected_sequence(direction)[1:],
        )

    @callback
    def _advance_sequence(self, entity_id: str, now: datetime) -> None:
        """Consume one sensor event inside an already open sequence."""
        assert self._direction is not None  # guarded by the caller
        expected = self._config.expected_sequence(self._direction)
        step = len(self._progress)

        if entity_id in self._progress:
            # PIR sensors bounce; re-triggering an already matched sensor is
            # normal and must not invalidate the sequence.
            _LOGGER.debug(
                "Gate '%s': %s re-triggered, sequence kept",
                self._config.name,
                entity_id,
            )
            return

        if entity_id != expected[step]:
            _LOGGER.warning(
                "Gate '%s': sequence discarded, expected %s but %s fired",
                self._config.name,
                expected[step],
                entity_id,
            )
            self._reset_sequence()
            # The stray event may legitimately open a new sequence.
            self._start_sequence(entity_id, now)
            return

        self._progress.append(entity_id)
        if len(self._progress) < len(expected):
            _LOGGER.debug(
                "Gate '%s': step %d/%d matched by %s",
                self._config.name,
                len(self._progress),
                len(expected),
                entity_id,
            )
            return

        self._complete_sequence(now)

    @callback
    def _complete_sequence(self, now: datetime) -> None:
        """Register the transit and re-arm the gate."""
        assert self._direction is not None and self._started is not None
        direction = self._direction
        started = self._started
        sensors = list(self._progress)

        from_area, to_area = self._config.areas_for(direction)
        record = TransitRecord(
            gate_id=self._config.gate_id,
            gate_name=self._config.name,
            direction=direction,
            from_area=from_area,
            to_area=to_area,
            from_area_name=self._resolve_area_name(from_area),
            to_area_name=self._resolve_area_name(to_area),
            started=started,
            ended=now,
            duration=(now - started).total_seconds(),
            sensors=sensors,
            boundary_used=self._config.sensor_boundary is not None,
        )

        self._reset_sequence()
        if self._config.cooldown > 0:
            self._cooldown_until = now + timedelta(seconds=self._config.cooldown)

        _LOGGER.info(
            "Transit on gate '%s': %s -> %s in %.1fs",
            record.gate_name,
            record.from_area_name,
            record.to_area_name,
            record.duration,
        )
        self._on_transit(record)

    @callback
    def _async_sequence_timeout(self, _now: datetime) -> None:
        """Drop the sequence that failed to complete in time."""
        self._timeout_unsub = None
        if self._direction is None:
            return
        _LOGGER.warning(
            "Gate '%s': sequence expired after %.0fs with %d/%d steps matched",
            self._config.name,
            self._config.sequence_timeout,
            len(self._progress),
            len(self._config.expected_sequence(self._direction)),
        )
        self._reset_sequence()

    @callback
    def _reset_sequence(self) -> None:
        """Clear the active sequence and its timeout."""
        if self._timeout_unsub is not None:
            self._timeout_unsub()
            self._timeout_unsub = None
        self._direction = None
        self._progress = []
        self._started = None
