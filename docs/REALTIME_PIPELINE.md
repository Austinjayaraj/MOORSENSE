# Real-Time Pipeline

## Architecture

```
INCOIS (Official OMNI Portal)
   ↓
IncoisBuoyProvider (HTTP + HTML parser)
   ↓
Telemetry Normalizer (combine_series)
   ↓
BuoyIngestionWorker (poll_once)
   ↓
EventOutbox (SQLite durable dedup)
   ↓
Kafka Producer (moorsense.telemetry)
   ↓
 ┌─────────────────────────────────┐
 │                                 │
 ↓                                 ↓
Persistence Consumer          UI Consumer
(Kafka → PostgreSQL)          (Kafka → Cache → WebSocket)
                                   │
                                   ├→ Mooring Calculator
                                   │   (physics_service)
                                   │
                                   ↓
                              WebSocket → React Frontend
```

## Pipeline Stages

### 1. Source Polling (IncoisBuoyProvider)

- Polls INCOIS every `BUOY_POLL_INTERVAL_SECONDS` (minimum 60s)
- Retrieves station catalog via WFS GeoJSON
- Fetches core parameters (air_temperature, air_pressure) every cycle
- Fetches supplementary parameters hourly
- Rate limited: max 3 concurrent requests

### 2. Normalization (telemetry_normalizer)

- Parses embedded Highcharts JSON from HTML
- Validates source epochs (no future timestamps)
- Preserves zero values and null readings
- Combines series only when source epochs match exactly
- No interpolation or carry-forward

### 3. Deduplication (EventOutbox)

- SQLite-based durable journal
- Key: `buoyId:observation_timestamp`
- INSERT OR IGNORE prevents duplicate entries
- Survives process restarts
- At-most-once publication per observation

### 4. Kafka Publication

- Topic: `moorsense.telemetry`
- Partition key: buoy ID
- Idempotent producer
- Exponential backoff retry on connection failure
- Outbox entries marked as published after broker acknowledgment

### 5. Persistence Consumer

- Consumer group: `moorsense.telemetry.persistence`
- Writes to PostgreSQL `buoy_observations` table
- `ON CONFLICT (event_id) DO NOTHING` for idempotent storage
- Append-only: old observations are NEVER replaced or deleted
- Automatic reconnection with retry

### 6. UI Consumer

- Consumer group: unique per API instance
- Updates in-memory latest-state cache
- Broadcasts to subscribed WebSocket clients
- Triggers mooring calculation on genuinely new observations
- Prevents old events from replacing newer state

### 7. Mooring Calculation (on new observation)

1. Load buoy-specific mooring configuration
2. Compute environmental forces (wind, current, wave)
3. Compute catenary mooring response per line
4. Persist estimate to `mooring_estimates` table
5. Update latest digital twin state in memory

### 8. WebSocket Delivery

- Endpoint: `/ws/buoys`
- Subscribe/unsubscribe per buoy ID
- Heartbeat: status updates every 15s on idle
- Reconnection with exponential backoff
- Origin allowlist enforcement

## Freshness Classification

| State | Criteria |
|-------|---------|
| FRESH | Observation age < cadence threshold (default 3h) |
| LATEST_AVAILABLE | Age between cadence and 2× cadence; source reachable |
| STALE | Age exceeds 2× cadence |
| OFFLINE | No observation or age > 24h |
| SOURCE_UNAVAILABLE | Source request/parser/access failure |

Cadence is configurable via `BUOY_SOURCE_CADENCE_SECONDS` (default 10800 = 3h).

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| BUOY_POLL_INTERVAL_SECONDS | 60 | Polling interval (minimum 60) |
| BUOY_LIVE_THRESHOLD_SECONDS | 10800 | FRESH threshold (cadence) |
| BUOY_STALE_THRESHOLD_SECONDS | 21600 | STALE threshold (2× cadence) |
| BUOY_OFFLINE_THRESHOLD_SECONDS | 86400 | OFFLINE threshold |
| BUOY_SOURCE_CADENCE_SECONDS | 10800 | Expected source cadence |
| KAFKA_BOOTSTRAP_SERVERS | localhost:9092 | Kafka brokers |
| BUOY_DATABASE_URL | postgresql://... | PostgreSQL DSN |
| BUOY_OUTBOX_PATH | data/buoy_outbox.sqlite3 | SQLite outbox path |
| BUOY_INGESTION_ENABLED | true | Enable ingestion worker |
| BUOY_WS_ALLOWED_ORIGINS | localhost variants | WebSocket origin allowlist |

## Docker Compose

```sh
docker compose -f compose.buoys.yaml up -d
```

Starts Kafka (port 9092) and PostgreSQL (port 15432).

## Running

```sh
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend (separate terminal):
```sh
npm run dev
```
