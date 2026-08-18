# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres to [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-08-18

### Added

- Hub summary device, one per config entry, aggregating cross-gate activity
  that does not belong to a single gate or area (SPEC 4):
  - `sensor.area_transit_hub_last_path`: the last completed multi-gate path
    (SPEC 3), previously only available as the `area_transit_path` bus event.
  - `sensor.area_transit_hub_total_transits`: transits registered across
    every gate, regardless of direction.
  - `area_transit.reset_counters` targeted at the hub device now resets both.
- Local brand images (`custom_components/area_transit/brand/icon.png`,
  `logo.png`), required since Home Assistant 2026.3 for the icon to show in
  the integrations list; the repository-root `icon.png`/`logo.png` are kept
  for the HACS store listing.
- Localisation of the new entities and service description in English,
  Italian, French, Spanish and German.

## [1.0.0] - 2026-08-17

### Added

- First release, built from [SPEC.md](SPEC.md) v1.0.0.
- Hub config entry with one `gate` subentry per monitored gate, configured
  entirely from the UI (SPEC 1).
- Ordered sequence detection with an optional — but, once configured,
  mandatory — boundary sensor, per-gate timeout and cooldown (SPEC 2).
- Chaining of contiguous gates into a single journey within a global
  inter-gate window, emitted as `area_transit_path` (SPEC 3).
- Per gate: last transit, direction and one counter per direction.
  Per area: estimated occupancy, clamped at zero. All restored on restart
  (SPEC 4).
- Services `reset_occupancy` and `reset_counters` (SPEC 5).
- Bus events `area_transit_transit` and `area_transit_path` (SPEC 6).
- Localisation in English, Italian, French, Spanish and German.
- Logic tests of the state machine and of the chain detector.
