"""Tests of the transit sequence and of the multi-gate chaining.

Covers SPEC.md section 2 (ordered sequence, mandatory boundary, timeout,
cooldown) and section 3 (contiguous gates, inter-gate window, U-turns).
"""

from __future__ import annotations

import pytest

from custom_components.area_transit.chain import ChainDetector
from custom_components.area_transit.const import (
    DIRECTION_IN_TO_OUT,
    DIRECTION_OUT_TO_IN,
)
from custom_components.area_transit.gate import GateTracker
from custom_components.area_transit.models import GateConfig, TransitRecord

SENSOR_A = "binary_sensor.area_a_motion"
SENSOR_B = "binary_sensor.area_b_motion"
SENSOR_C = "binary_sensor.area_c_motion"
BOUNDARY = "binary_sensor.gate_boundary"


def make_gate(
    *,
    gate_id: str = "gate1",
    name: str = "Gate 1",
    area_in: str = "area_a",
    area_out: str = "area_b",
    sensor_in: str = SENSOR_A,
    sensor_out: str = SENSOR_B,
    boundary: str | None = BOUNDARY,
    timeout: float = 10.0,
    cooldown: float = 5.0,
) -> GateConfig:
    """Build a gate configuration with sensible test defaults."""
    return GateConfig(
        gate_id=gate_id,
        name=name,
        area_in=area_in,
        area_out=area_out,
        sensor_in=sensor_in,
        sensor_out=sensor_out,
        sensor_boundary=boundary,
        sequence_timeout=timeout,
        cooldown=cooldown,
    )


@pytest.fixture
def transits() -> list[TransitRecord]:
    """Collect the transits produced during a test."""
    return []


def start_tracker(
    hass, config: GateConfig, transits: list[TransitRecord]
) -> GateTracker:
    """Create and arm a tracker recording its transits into `transits`."""
    tracker = GateTracker(hass, config, transits.append, lambda area_id: area_id)
    tracker.async_start()
    return tracker


# --- SPEC 2: single gate sequence ------------------------------------------


def test_full_sequence_registers_transit(hass, transits) -> None:
    """A -> boundary -> B within the timeout registers one transit."""
    start_tracker(hass, make_gate(), transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)

    assert len(transits) == 1
    record = transits[0]
    assert record.direction == DIRECTION_IN_TO_OUT
    assert record.from_area == "area_a"
    assert record.to_area == "area_b"
    assert record.duration == pytest.approx(2.0)
    assert record.boundary_used is True


def test_reverse_sequence_registers_opposite_direction(hass, transits) -> None:
    """B -> boundary -> A is registered in the opposite direction."""
    start_tracker(hass, make_gate(), transits)

    hass.fire(SENSOR_B)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_A)

    assert len(transits) == 1
    assert transits[0].direction == DIRECTION_OUT_TO_IN
    assert transits[0].from_area == "area_b"


def test_missing_boundary_discards_sequence(hass, transits) -> None:
    """With a boundary configured, A -> B alone registers nothing (SPEC 2)."""
    start_tracker(hass, make_gate(), transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(SENSOR_B)
    hass.advance(30)

    assert transits == []


def test_gate_without_boundary_needs_two_sensors_only(hass, transits) -> None:
    """A gate configured without a boundary works with two sensors."""
    start_tracker(hass, make_gate(boundary=None), transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(SENSOR_B)

    assert len(transits) == 1
    assert transits[0].boundary_used is False


def test_sequence_expires_after_timeout(hass, transits) -> None:
    """A sequence that does not complete in time is dropped."""
    start_tracker(hass, make_gate(timeout=10), transits)

    hass.fire(SENSOR_A)
    hass.advance(4)
    hass.fire(BOUNDARY)
    hass.advance(11)
    hass.fire(SENSOR_B)

    assert transits == []


def test_retrigger_does_not_break_sequence(hass, transits) -> None:
    """A PIR bouncing on an already matched sensor is ignored."""
    start_tracker(hass, make_gate(), transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)

    assert len(transits) == 1


def test_cooldown_blocks_immediate_second_transit(hass, transits) -> None:
    """No new sequence is accepted while the cooldown is running."""
    start_tracker(hass, make_gate(cooldown=5), transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    assert len(transits) == 1

    # Within the cooldown: everything is ignored.
    hass.advance(1)
    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    assert len(transits) == 1

    # After the cooldown the gate works again.
    hass.advance(10)
    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    assert len(transits) == 2


def test_boundary_alone_never_starts_a_sequence(hass, transits) -> None:
    """The boundary carries no direction, so it cannot open a sequence."""
    start_tracker(hass, make_gate(), transits)

    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    hass.advance(30)

    assert transits == []


def test_stop_releases_subscriptions(hass, transits) -> None:
    """A stopped tracker no longer reacts to its sensors."""
    tracker = start_tracker(hass, make_gate(), transits)
    tracker.async_stop()

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)

    assert transits == []


# --- SPEC 3: multi-gate chaining -------------------------------------------


def chain_setup(hass, window: float = 20.0):
    """Return a chain detector and the list collecting its paths."""
    paths: list = []
    return ChainDetector(hass, window, paths.append), paths


def run_two_gates(hass, transits, gap: float) -> None:
    """Walk A -> B through gate 1, wait `gap`, then B -> C through gate 2."""
    gate1 = make_gate(
        gate_id="gate1", name="Gate A-B", area_in="area_a", area_out="area_b"
    )
    gate2 = make_gate(
        gate_id="gate2",
        name="Gate B-C",
        area_in="area_b",
        area_out="area_c",
        sensor_in=SENSOR_B,
        sensor_out=SENSOR_C,
        boundary=None,
        cooldown=0,
    )
    start_tracker(hass, gate1, transits)
    start_tracker(hass, gate2, transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    hass.advance(gap)
    hass.fire(SENSOR_B)
    hass.advance(1)
    hass.fire(SENSOR_C)


def test_contiguous_gates_build_a_path(hass, transits) -> None:
    """Two contiguous transits inside the window produce one path A -> C."""
    detector, paths = chain_setup(hass, window=20)
    run_two_gates(hass, transits, gap=3)
    for record in transits:
        detector.async_add_transit(record)

    assert len(transits) == 2
    assert paths == []  # not emitted yet, the window is still open

    hass.advance(21)
    assert len(paths) == 1
    path = paths[0]
    assert path.origin == "area_a"
    assert path.destination == "area_c"
    assert path.via == ["area_b"]
    assert len(path.transits) == 2


def test_gap_longer_than_window_produces_no_path(hass, transits) -> None:
    """Beyond the inter-gate window the two transits stay independent."""
    detector, paths = chain_setup(hass, window=5)
    gate1 = make_gate(gate_id="gate1", area_in="area_a", area_out="area_b")
    gate2 = make_gate(
        gate_id="gate2",
        area_in="area_b",
        area_out="area_c",
        sensor_in=SENSOR_B,
        sensor_out=SENSOR_C,
        boundary=None,
        cooldown=0,
    )
    start_tracker(hass, gate1, transits)
    start_tracker(hass, gate2, transits)

    hass.fire(SENSOR_A)
    hass.advance(1)
    hass.fire(BOUNDARY)
    hass.advance(1)
    hass.fire(SENSOR_B)
    detector.async_add_transit(transits[0])

    hass.advance(30)
    hass.fire(SENSOR_B)
    hass.advance(1)
    hass.fire(SENSOR_C)
    detector.async_add_transit(transits[1])
    hass.advance(10)

    assert len(transits) == 2
    assert paths == []


def test_u_turn_is_not_chained(hass) -> None:
    """Going back to an already crossed area starts a new path."""
    detector, paths = chain_setup(hass, window=20)
    from datetime import timedelta

    from custom_components.area_transit.gate import dt_util

    def record(gate_id: str, src: str, dst: str, offset: float) -> TransitRecord:
        started = dt_util.utcnow() + timedelta(seconds=offset)
        return TransitRecord(
            gate_id=gate_id,
            gate_name=gate_id,
            direction=DIRECTION_IN_TO_OUT,
            from_area=src,
            to_area=dst,
            from_area_name=src,
            to_area_name=dst,
            started=started,
            ended=started + timedelta(seconds=1),
            duration=1.0,
            sensors=[],
            boundary_used=False,
        )

    detector.async_add_transit(record("gate1", "area_a", "area_b", 0))
    detector.async_add_transit(record("gate2", "area_b", "area_a", 3))
    hass.advance(30)

    assert paths == []
