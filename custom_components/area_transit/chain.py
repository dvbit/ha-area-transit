"""Multi-gate path detection for the Area Transit integration.

Implements SPEC.md section 3: when a transit through gate 1 (area A -> area B)
is followed, within `inter_gate_window` seconds, by a transit through a
contiguous gate 2 (area B -> area C), the two movements are considered a
single journey A -> C via B.

The path is emitted only once the window expires without further extensions,
so `A -> B -> C -> D` produces one `area_transit_path` event describing the
whole journey instead of one event per intermediate leg. The individual
transits are always registered independently (SPEC 3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
import logging

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later

from .const import MAX_PATH_GATES
from .models import PathRecord, TransitRecord

_LOGGER = logging.getLogger(__name__)

#: Callback invoked once a path is final.
type PathCallback = Callable[[PathRecord], None]


@dataclass(slots=True, eq=False)  # identity comparison: two paths never merge
class _OpenPath:
    """A path still accepting extensions, with its expiry timer."""

    record: PathRecord
    unsub: CALLBACK_TYPE | None = field(default=None)


class ChainDetector:
    """Aggregate contiguous transits into paths."""

    def __init__(
        self, hass: HomeAssistant, window: float, on_path: PathCallback
    ) -> None:
        """Initialise the detector with the configured inter-gate window."""
        self._hass = hass
        self._window = window
        self._on_path = on_path
        self._open: list[_OpenPath] = []

    # -- public API ----------------------------------------------------------

    @callback
    def async_add_transit(self, transit: TransitRecord) -> None:
        """Extend an existing path with `transit`, or open a new one."""
        if (candidate := self._find_extendable(transit)) is not None:
            self._cancel(candidate)
            candidate.record.transits.append(transit)
            self._arm(candidate)
            _LOGGER.debug(
                "Path extended: %s -> %s via %s (%d gates)",
                candidate.record.origin_name,
                candidate.record.destination_name,
                candidate.record.via_names,
                len(candidate.record.transits),
            )
            return

        opened = _OpenPath(record=PathRecord(transits=[transit]))
        self._open.append(opened)
        self._arm(opened)
        _LOGGER.debug(
            "Path candidate opened at gate '%s', waiting %.0fs for a next transit",
            transit.gate_name,
            self._window,
        )

    @callback
    def async_stop(self) -> None:
        """Drop every pending path without emitting it."""
        for opened in self._open:
            self._cancel(opened)
        self._open.clear()
        _LOGGER.debug("Chain detector stopped, pending paths dropped")

    # -- internals -----------------------------------------------------------

    @callback
    def _find_extendable(self, transit: TransitRecord) -> _OpenPath | None:
        """Return the open path `transit` may continue, if any.

        A path is extendable when the new transit starts where the path
        currently ends, crosses a different gate, arrives within the window and
        does not revisit an area already crossed (a U-turn is a new journey,
        not a continuation).
        """
        best: _OpenPath | None = None
        for opened in self._open:
            last = opened.record.transits[-1]
            if last.gate_id == transit.gate_id:
                continue
            if last.to_area != transit.from_area:
                continue
            if len(opened.record.transits) >= MAX_PATH_GATES:
                _LOGGER.debug(
                    "Path at gate '%s' reached the %d gates cap, not extended",
                    last.gate_name,
                    MAX_PATH_GATES,
                )
                continue
            if transit.to_area in opened.record.visited_areas:
                _LOGGER.debug(
                    "Transit through '%s' returns to an already crossed area, "
                    "starting a new path",
                    transit.gate_name,
                )
                continue
            if not self._within_window(last.ended, transit.started):
                continue
            if best is None or last.ended > best.record.transits[-1].ended:
                best = opened
        return best

    def _within_window(self, previous_end: datetime, new_start: datetime) -> bool:
        """Return True when the two legs are close enough in time."""
        delta = (new_start - previous_end).total_seconds()
        return 0 <= delta <= self._window

    @callback
    def _arm(self, opened: _OpenPath) -> None:
        """(Re)start the expiry timer of a path."""
        opened.unsub = async_call_later(
            self._hass, self._window, lambda _now: self._async_expire(opened)
        )

    @callback
    def _cancel(self, opened: _OpenPath) -> None:
        """Cancel the expiry timer of a path."""
        if opened.unsub is not None:
            opened.unsub()
            opened.unsub = None

    @callback
    def _async_expire(self, opened: _OpenPath) -> None:
        """Close a path: emit it when it chains at least two gates."""
        opened.unsub = None
        if opened in self._open:
            self._open.remove(opened)

        record = opened.record
        if len(record.transits) < 2:
            _LOGGER.debug(
                "Path candidate from gate '%s' expired with a single transit",
                record.transits[0].gate_name,
            )
            return

        _LOGGER.info(
            "Path detected: %s -> %s via %s in %.1fs (%d gates)",
            record.origin_name,
            record.destination_name,
            ", ".join(record.via_names),
            record.duration,
            len(record.transits),
        )
        self._on_path(record)
