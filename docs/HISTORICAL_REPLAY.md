# Historical Replay Engine

## Purpose

Deterministically reproduce mooring Digital Twin calculations over a historical time window.
Every observation is processed using only data known at or before its timestamp.

## Temporal Safety Guarantee

At timestamp T:
- Only telemetry with observation_timestamp ≤ T is used
- Only mooring configurations with valid_from ≤ T (and valid_to > T) are used
- No future bathymetry, model parameters, or configurations leak in
- Each observation is processed independently — no cross-observation state

## Usage

```python
from services.replay.replay_runner import ReplayRunner, ReplayObservation

runner = ReplayRunner()
observations = [
    ReplayObservation(
        station_id="OMNI-BD10",
        observation_timestamp=datetime(2026, 10, 8, 3, 0, tzinfo=timezone.utc),
        telemetry={...})
]
results = runner.replay_observations("OMNI-BD10", observations)
```

## Output

Each `ReplayResult` contains:
- `observation_timestamp` — the source observation timestamp
- `telemetry_snapshot` — the telemetry used
- `mooring_response` — full MooringResponse with provenance
- `model_versions` — model/physics/configuration version stack
- `replay_created_at` — when the replay was computed (not the observation time)

## Configuration Versioning

Uses `MooringConfigRegistry.resolve_at(station_id, timestamp)` to find the
correct configuration version for each timestamp. Currently all configurations
are REFERENCE class — no authoritative deployment records exist.

## Limitations

- No future-configuration leakage (enforced by valid_from/valid_to guards)
- Replay uses the same reference configuration for all timestamps (no deployment history)
- Physics model is quasi-static screening-level — no dynamic analysis
- Missing wave/current data remains UNKNOWN — not filled from climatology
