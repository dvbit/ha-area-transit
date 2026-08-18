<p align="center">
  <img src="icon.png" alt="Area Transit" width="128" height="128">
</p>

<h1 align="center">Area Transit</h1>

<p align="center">
  Detect people moving from one area to another, with direction, counters and
  estimated occupancy — using the motion sensors you already own.
</p>

<p align="center">
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg" alt="HACS custom"></a>
  <img src="https://img.shields.io/badge/version-1.1.0-blue.svg" alt="Version 1.1.0">
  <img src="https://img.shields.io/badge/Home%20Assistant-2025.6%2B-41BDF5.svg" alt="Home Assistant 2025.6+">
</p>

> 🇮🇹 [Leggi questa pagina in italiano](README.it.md) — 📄 [Specification](SPEC.md)

## What it does

A **gate** is the boundary between two areas. Area Transit watches the sensors
around that boundary and registers a transit **only when they fire in the right
order**, within a configurable time window:

```
             ┌──────────┐   ┌──────────┐
   Area A    │ boundary │   │  Area B
   sensor  ──┼──────────┼──▶│  sensor
             └──────────┘   └──────────┘
        1st        2nd            3rd     →  transit A ➜ B
```

The boundary sensor is optional. Once you configure one it becomes mandatory:
without its trigger the sequence is discarded, which is what keeps false
positives away.

Contiguous gates are chained: if someone crosses `Hallway ➜ Corridor` and then
`Corridor ➜ Bedroom` shortly after, a single **path** `Hallway ➜ Bedroom via
Corridor` is reported on top of the two individual transits.

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories**
2. Repository `https://github.com/dvbit/ha-area-transit`, category **Integration**
3. Install **Area Transit**, then restart Home Assistant
4. **Settings → Devices & services → Add integration → Area Transit**

### Manual

Copy `custom_components/area_transit` into your `config/custom_components/`
folder and restart Home Assistant.

## Configuration

Adding the integration only asks for the **inter-gate window** — the maximum
delay between two transits for them to count as one journey.

Then add one gate at a time from the integration page
(**Add gate**):

| Field | Meaning | Default |
| --- | --- | --- |
| Name | Device name of the gate | — |
| Area A / Area B | The two areas connected by the gate | — |
| Motion sensor in area A / B | One `binary_sensor` per area, close to the gate | — |
| Boundary sensor | Optional. **Mandatory in the sequence once set** | — |
| Sequence timeout | Max time between the first and the last sensor | 10 s |
| Cooldown | Time the gate ignores events after a transit | 5 s |

Gates can be edited or removed at any time; the integration reloads itself.

## Entities

For each gate (device = the gate):

| Entity | Example | Description |
| --- | --- | --- |
| Last transit | `sensor.corridor_gate_last_transit` | Timestamp of the last transit. Attributes: `direction`, `from_area`, `to_area`, `duration`, `sensors`, `boundary_used` |
| Direction | `sensor.corridor_gate_direction` | `in_to_out` (A ➜ B) or `out_to_in` (B ➜ A) |
| Transits A to B | `sensor.corridor_gate_transits_a_to_b` | Counter |
| Transits B to A | `sensor.corridor_gate_transits_b_to_a` | Counter |

For each monitored area (device = the area):

| Entity | Example | Description |
| --- | --- | --- |
| Estimated occupancy | `sensor.living_room_estimated_occupancy` | People count, `+1` on arrival, `-1` on departure, never below zero |

On the single **Area Transit Hub** device (one per config entry, aggregates activity across every gate):

| Entity | Example | Description |
| --- | --- | --- |
| Last path | `sensor.area_transit_hub_last_path` | Timestamp of the last completed multi-gate path. Attributes: `origin`, `destination`, `via`, `gates`, `duration` |
| Total transits | `sensor.area_transit_hub_total_transits` | Transits registered across every gate, regardless of direction |

All values survive a Home Assistant restart.

## Services

```yaml
# Realign the estimated occupancy of an area
action: area_transit.reset_occupancy
target:
  entity_id: sensor.living_room_estimated_occupancy
data:
  value: 0

# Reset the counters, the last transit and the direction of a gate
# (targeting the gate device resets all of its entities at once)
action: area_transit.reset_counters
target:
  device_id: 1a2b3c4d5e6f
```

## Events

### `area_transit_transit`

```json
{
  "gate_id": "01JABCDEF...",
  "gate_name": "Corridor gate",
  "direction": "in_to_out",
  "from_area_id": "hallway",
  "from_area": "Hallway",
  "to_area_id": "living_room",
  "to_area": "Living room",
  "started": "2026-08-17T18:04:11.120000+00:00",
  "ended": "2026-08-17T18:04:13.480000+00:00",
  "duration": 2.36,
  "sensors": ["binary_sensor.hallway_motion", "binary_sensor.gate_boundary", "binary_sensor.living_room_motion"],
  "boundary_used": true
}
```

### `area_transit_path`

```json
{
  "origin_id": "hallway",
  "origin": "Hallway",
  "destination_id": "bedroom",
  "destination": "Bedroom",
  "via_ids": ["corridor"],
  "via": ["Corridor"],
  "gates": ["Hallway gate", "Bedroom gate"],
  "started": "2026-08-17T18:04:11.120000+00:00",
  "ended": "2026-08-17T18:04:22.900000+00:00",
  "duration": 11.78,
  "transits": []
}
```

## Usage examples

### Turn the light on only when someone *enters* the room

```yaml
automation:
  - alias: "Living room light on entry"
    triggers:
      - trigger: event
        event_type: area_transit_transit
        event_data:
          to_area_id: living_room
    actions:
      - action: light.turn_on
        target:
          entity_id: light.living_room
```

### Notify when someone walks from the entrance to the bedroom

```yaml
automation:
  - alias: "Entrance to bedroom"
    triggers:
      - trigger: event
        event_type: area_transit_path
    conditions:
      - condition: template
        value_template: >
          {{ trigger.event.data.origin_id == 'entrance'
             and trigger.event.data.destination_id == 'bedroom' }}
    actions:
      - action: notify.mobile_app_phone
        data:
          message: >
            Someone went from {{ trigger.event.data.origin }} to
            {{ trigger.event.data.destination }} via
            {{ trigger.event.data.via | join(', ') }}
            in {{ trigger.event.data.duration | round(1) }} s
```

### Switch everything off when an area empties

```yaml
automation:
  - alias: "Office empty"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.office_estimated_occupancy
        below: 1
        for: "00:05:00"
    actions:
      - action: light.turn_off
        target:
          area_id: office
```

### Nightly realignment of the estimates

Occupancy is an estimate and drifts over time (a window, a pet, a missed
sequence). A daily reset keeps it honest:

```yaml
automation:
  - alias: "Nightly occupancy reset"
    triggers:
      - trigger: time
        at: "04:00:00"
    actions:
      - action: area_transit.reset_occupancy
        target:
          entity_id:
            - sensor.living_room_estimated_occupancy
            - sensor.bedroom_estimated_occupancy
        data:
          value: 0
```

### Dashboard card

```yaml
type: entities
title: Corridor gate
entities:
  - entity: sensor.corridor_gate_last_transit
  - entity: sensor.corridor_gate_direction
  - entity: sensor.corridor_gate_transits_a_to_b
  - entity: sensor.corridor_gate_transits_b_to_a
  - entity: sensor.living_room_estimated_occupancy
```

## Sensor placement tips

* Point the two motion sensors **away from each other**, each covering its own
  side of the gate, so a single person cannot trigger both at once.
* Reduce overlapping coverage: a sensor seeing both sides breaks the ordering.
* If your PIRs have a long "on" hold time, keep the sequence timeout above it.
* Add the boundary sensor (a door sensor, a break-beam, a mmWave zone) whenever
  precision matters more than coverage.

## Troubleshooting

Enable debug logging to see every step of the state machine:

```yaml
logger:
  default: warning
  logs:
    custom_components.area_transit: debug
```

| Symptom | Likely cause |
| --- | --- |
| No transit at all | Boundary sensor configured but never firing, or sensors fire simultaneously |
| `sequence discarded, expected ...` | Overlapping sensor coverage, or reversed area assignment |
| `sequence expired` | Sequence timeout too short for the distance |
| Counters growing twice | Cooldown too short for your PIR hold time |
| Occupancy drifting | Normal for an estimate: schedule the nightly reset above |

## License

MIT — see [LICENSE](LICENSE).
