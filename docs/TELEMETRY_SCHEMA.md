# Telemetry Schema

## Canonical Measurement Format

Every measurement follows this schema:

```json
{
  "parameter": "air_temperature",
  "value": 28.418,
  "unit": "°C",
  "depth_m": null,
  "observation_timestamp": "2026-10-08T03:00:00+00:00",
  "source": "INCOIS",
  "source_epoch_ms": 1791428400000,
  "first_seen_timestamp": "2026-10-08T04:15:32+00:00",
  "received_timestamp": "2026-10-08T04:15:33+00:00",
  "quality": "NOMINAL",
  "availability": "measured"
}
```

## Profile Measurements

Depth-varying parameters include a `depth_m` field:

```json
{
  "parameter": "water_temperature",
  "value": 26.5,
  "unit": "°C",
  "depth_m": 20,
  "observation_timestamp": "2026-10-08T03:00:00+00:00",
  "source": "INCOIS",
  "availability": "measured"
}
```

## Telemetry Groups

### Meteorology
- `airTemperature` (°C)
- `pressure` (hPa)
- `humidity` (%)
- `rainfall` (mm)
- `radiation` (W/m²)
- `windSpeed` (m/s) — RESTRICTED on some stations
- `windDirection` (°) — RESTRICTED on some stations

### Ocean
- `sst` — Sea Surface Temperature (°C), from 1m depth profile
- `salinity` (PSU), from 1m depth profile
- `currentSpeed` (m/s) — NOT currently available from source
- `currentDirection` (°) — NOT currently available from source

### Waves
- `waveHeight` (m) — NOT currently available from source
- `wavePeriod` (s) — NOT currently available from source
- `waveDirection` (°) — NOT currently available from source

### Profiles
- `temperature` — array of `{depth, value, unit}` at discovered depths
- `salinity` — array of `{depth, value, unit}` at discovered depths

## Kafka Event Schema

Topic: `moorsense.telemetry`

```json
{
  "eventType": "BUOY_TELEMETRY",
  "eventId": "OMNI-BD14:2026-10-08T03:00:00+00:00",
  "buoyId": "OMNI-BD14",
  "timestamp": "2026-10-08T03:00:00+00:00",
  "observationTimestamp": "2026-10-08T03:00:00+00:00",
  "sourceTimestamp": "2026-10-08T03:00:00+00:00",
  "location": {"latitude": 6.570556, "longitude": 88.233333},
  "receivedAt": "2026-10-08T04:15:33+00:00",
  "source": "INCOIS",
  "telemetry": {
    "meteorology": {...},
    "ocean": {...},
    "waves": {...},
    "profiles": {...}
  },
  "rawPayload": {
    "sourceEpochMs": 1791428400000,
    "coordinateKind": "registry",
    "parameters": {...}
  }
}
```

## Deduplication

Key: `buoyId:observation_timestamp` (the `eventId`/`identity`)

The SQLite outbox prevents duplicate Kafka publication. PostgreSQL uses `ON CONFLICT (event_id) DO NOTHING` for idempotent storage. The in-memory cache only advances forward (newer timestamp replaces older).

## Timestamp Semantics

| Field | Meaning |
|-------|---------|
| `observation_timestamp` | When the physical measurement was taken (source epoch) |
| `first_seen_timestamp` | When MoorSense first retrieved this epoch (UTC provider only) |
| `received_timestamp` | When MoorSense processed/stored the observation |
| `source_publication_timestamp` | Explicitly null — source does not provide publication time |
