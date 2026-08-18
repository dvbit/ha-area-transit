# Area Transit — consolidated specification

Version 1.0.0 — the requirement this integration was built from, agreed before
any code was written. Every module references these section numbers in its
docstrings and comments.

## 1. Structure

* Custom Python integration, configured entirely from the UI.
* A single hub config entry (`single_config_entry`), holding the global
  settings. One `gate` **subentry** per monitored gate; each subentry creates
  its own device.
* A gate is defined by:
  * name;
  * area A and area B, picked from the Home Assistant area registry;
  * a motion `binary_sensor` in area A;
  * a motion `binary_sensor` in area B;
  * an optional boundary `binary_sensor`;
  * `sequence_timeout` (default 10 s);
  * `cooldown` (default 5 s).
* Adding, editing or removing a gate reloads the integration.

## 2. Transit detection

* Only the `off -> on` edge of a sensor is a detection.
* A valid sequence is:
  * `sensor area X -> sensor area Y` when no boundary sensor is configured;
  * `sensor area X -> boundary -> sensor area Y` when one is configured — once
    configured the boundary is **mandatory**.
* The whole sequence must complete within `sequence_timeout` seconds, counted
  from the first sensor.
* The direction is given by the area the sequence started from: `in_to_out`
  (A to B) or `out_to_in` (B to A).
* A sequence is discarded, with a log entry, when:
  * the timeout expires before the last step;
  * a sensor fires out of order (the stray event may open a new sequence);
  * the boundary is configured but does not fire.
* Re-triggering an already matched sensor does not invalidate the sequence
  (PIR sensors bounce).
* The boundary sensor alone never opens a sequence: it carries no direction.
* After a registered transit the gate ignores every event for `cooldown`
  seconds, to avoid double counting.

## 3. Gate chaining

* Two gates are contiguous when the destination area of the first transit is
  the origin area of the second one.
* When a contiguous transit arrives within `inter_gate_window` seconds
  (default 20 s, global setting), the two movements are merged into a single
  journey: `origin -> destination` `via` the shared area.
* The path keeps growing while further contiguous transits arrive in time, up
  to 10 gates, and is emitted once the window expires without extensions — so
  `A -> B -> C -> D` produces one event describing the whole journey.
* A transit returning to an already crossed area (U-turn) does not extend the
  path: it opens a new one.
* The individual transits are always registered independently: the counters of
  both gates increment and the net occupancy of the intermediate area returns
  to its previous value.

## 4. Entities

Per gate (device = the gate):

| Entity | Description |
| --- | --- |
| `sensor.<gate>_last_transit` | Timestamp of the last transit, with direction, areas, duration and sensors as attributes |
| `sensor.<gate>_direction` | Direction of the last transit (`in_to_out` / `out_to_in`) |
| `sensor.<gate>_transits_a_to_b` | Number of transits from area A to area B |
| `sensor.<gate>_transits_b_to_a` | Number of transits from area B to area A |

Per monitored area (device = the area):

| Entity | Description |
| --- | --- |
| `sensor.<area>_estimated_occupancy` | Estimated people count, incremented and decremented by the transits, never negative |

On the single hub device (one per config entry, aggregates activity across every gate):

| Entity | Description |
| --- | --- |
| `sensor.area_transit_hub_last_path` | Timestamp of the last completed multi-gate path (SPEC 3), with origin, destination, via areas, gates and duration as attributes |
| `sensor.area_transit_hub_total_transits` | Number of transits registered across every gate, regardless of direction |

Every value is restored after a Home Assistant restart.

## 5. Services

| Service | Effect |
| --- | --- |
| `area_transit.reset_occupancy` | Sets the occupancy of the targeted areas to `value` (default 0) |
| `area_transit.reset_counters` | Resets the counters, the last transit and the direction of the targeted gates. Targeting the hub device resets the last path and the total transits counter |

Both are entity services: they accept an entity, a device (gate, area or hub) or an area as target.

## 6. Bus events

* `area_transit_transit` — one per validated transit.
* `area_transit_path` — one per completed multi-gate path.

## 7. Logging

| Level | Content |
| --- | --- |
| `DEBUG` | Every sensor edge, state machine steps, restores, cooldown hits |
| `INFO` | Registered transits, detected paths, resets, start-up summary |
| `WARNING` | Sequences discarded (timeout, wrong order), missing area |
| `ERROR` | Invalid gate configuration |

## 8. Packaging

* HACS-compatible repository, `custom_components/area_transit/`.
* Localisation in English, Italian, French, Spanish and German.
* README in English and Italian, with usage examples.
* Representative icon, `hacs.json`, `manifest.json` with an explicit version.
* Icon assets:
  * `assets/icon.png` (256x256), referenced by both READMEs;
  * `custom_components/area_transit/icon.svg`, the vector source;
  * `custom_components/area_transit/brand/` with `icon.png`, `logo.png`
    (256x256) and `icon@2x.png`, `logo@2x.png` (512x512), served by the
    Home Assistant brands proxy API so the integration shows its own icon.
