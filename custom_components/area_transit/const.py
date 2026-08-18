"""Constants for the Area Transit integration.

Reference: SPEC.md sections 1 (structure), 2 (detection), 3 (gate chaining).
Every key defined here is persisted either in the hub config entry options
(global settings) or in a `gate` subentry (per-gate settings).
"""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

# --- Integration identity ---------------------------------------------------

DOMAIN: Final = "area_transit"
PLATFORMS: Final[list[Platform]] = [Platform.SENSOR]

#: Subentry type used for every monitored gate (SPEC 1: one subentry per gate).
SUBENTRY_TYPE_GATE: Final = "gate"

# --- Configuration keys -----------------------------------------------------

# Global options, stored on the hub config entry (SPEC 3).
CONF_INTER_GATE_WINDOW: Final = "inter_gate_window"

# Per-gate options, stored on the gate subentry (SPEC 1 and 2).
CONF_AREA_IN: Final = "area_in"
CONF_AREA_OUT: Final = "area_out"
CONF_SENSOR_IN: Final = "sensor_in"
CONF_SENSOR_OUT: Final = "sensor_out"
CONF_SENSOR_BOUNDARY: Final = "sensor_boundary"
CONF_SEQUENCE_TIMEOUT: Final = "sequence_timeout"
CONF_COOLDOWN: Final = "cooldown"

# --- Defaults (SPEC 2 and 3) ------------------------------------------------

#: Max seconds between the first and the last sensor of a single sequence.
DEFAULT_SEQUENCE_TIMEOUT: Final = 10.0
#: Seconds a gate stays deaf after a registered transit (anti double count).
DEFAULT_COOLDOWN: Final = 5.0
#: Max seconds between two consecutive gate transits to build a path.
DEFAULT_INTER_GATE_WINDOW: Final = 20.0

#: Hard bounds used by the config flow selectors, kept here so the schema and
#: the runtime validation cannot drift apart.
MIN_SEQUENCE_TIMEOUT: Final = 1.0
MAX_SEQUENCE_TIMEOUT: Final = 300.0
MIN_COOLDOWN: Final = 0.0
MAX_COOLDOWN: Final = 300.0
MIN_INTER_GATE_WINDOW: Final = 1.0
MAX_INTER_GATE_WINDOW: Final = 600.0

#: Safety cap on how many gates a single path may chain (SPEC 3).
MAX_PATH_GATES: Final = 10

# --- Directions (SPEC 2) ----------------------------------------------------

#: Transit from `area_in` towards `area_out`.
DIRECTION_IN_TO_OUT: Final = "in_to_out"
#: Transit from `area_out` towards `area_in`.
DIRECTION_OUT_TO_IN: Final = "out_to_in"
DIRECTIONS: Final[list[str]] = [DIRECTION_IN_TO_OUT, DIRECTION_OUT_TO_IN]

# --- Bus events (SPEC 6) ----------------------------------------------------

#: Fired for every validated single-gate transit.
EVENT_TRANSIT: Final = f"{DOMAIN}_transit"
#: Fired for every multi-gate path (A -> B -> C) built by the chain detector.
EVENT_PATH: Final = f"{DOMAIN}_path"

# --- Event / state attributes ----------------------------------------------

ATTR_GATE_ID: Final = "gate_id"
ATTR_GATE_NAME: Final = "gate_name"
ATTR_DIRECTION: Final = "direction"
ATTR_FROM_AREA: Final = "from_area"
ATTR_FROM_AREA_ID: Final = "from_area_id"
ATTR_TO_AREA: Final = "to_area"
ATTR_TO_AREA_ID: Final = "to_area_id"
ATTR_STARTED: Final = "started"
ATTR_ENDED: Final = "ended"
ATTR_DURATION: Final = "duration"
ATTR_SENSORS: Final = "sensors"
ATTR_BOUNDARY_USED: Final = "boundary_used"
ATTR_ORIGIN: Final = "origin"
ATTR_ORIGIN_ID: Final = "origin_id"
ATTR_DESTINATION: Final = "destination"
ATTR_DESTINATION_ID: Final = "destination_id"
ATTR_VIA: Final = "via"
ATTR_VIA_IDS: Final = "via_ids"
ATTR_GATES: Final = "gates"
ATTR_TRANSITS: Final = "transits"
ATTR_VALUE: Final = "value"

# --- Entity translation keys (SPEC 4) --------------------------------------

KEY_LAST_TRANSIT: Final = "last_transit"
KEY_DIRECTION: Final = "direction"
KEY_COUNT_IN_TO_OUT: Final = "transits_in_to_out"
KEY_COUNT_OUT_TO_IN: Final = "transits_out_to_in"
KEY_OCCUPANCY: Final = "occupancy"
#: Hub summary entities (SPEC 4): last multi-gate path and overall transit count.
KEY_LAST_PATH: Final = "last_path"
KEY_TOTAL_TRANSITS: Final = "total_transits"

# --- Services (SPEC 5) ------------------------------------------------------

SERVICE_RESET_OCCUPANCY: Final = "reset_occupancy"
SERVICE_RESET_COUNTERS: Final = "reset_counters"

# --- Device registry --------------------------------------------------------

MANUFACTURER: Final = "Area Transit"
MODEL_GATE: Final = "Gate"
MODEL_AREA: Final = "Monitored area"
MODEL_HUB: Final = "Hub"
#: Name of the single summary device aggregating hub-wide entities (SPEC 4).
HUB_DEVICE_NAME: Final = "Area Transit Hub"
