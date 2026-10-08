import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
import asyncpg

log = logging.getLogger(__name__)

class ObservationStore:
    def __init__(self, dsn):
        self.dsn, self.pool = dsn, None
        self.connect_lock = asyncio.Lock()

    async def connect(self):
        # REST history and the persistence consumer can initialize concurrently.
        async with self.connect_lock:
            if self.pool is not None: return
            pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=3, timeout=5, command_timeout=10)
            try:
                async with pool.acquire() as connection:
                    async with connection.transaction():
                        # Serialize idempotent schema changes across API processes.
                        await connection.execute("SELECT pg_advisory_xact_lock(67490231)")
                        migrations_dir = Path(__file__).parents[2] / "migrations"
                        for migration in sorted(migrations_dir.glob("*.sql")):
                            await connection.execute(migration.read_text())
            except BaseException:
                await pool.close()
                raise
            self.pool = pool

    async def save(self, event):
        await self.connect()
        # All flattened values are in canonical units; the full normalized event
        # retains units and provider payload so no measurements lose provenance.
        expected = [
            ("meteorology", "windSpeed", "m/s"),
            ("meteorology", "windDirection", "°"),
            ("meteorology", "airTemperature", "°C"),
            ("meteorology", "pressure", "hPa"),
            ("meteorology", "humidity", "%"),
            ("meteorology", "rainfall", "mm"),
            ("ocean", "sst", "°C"),
            ("ocean", "salinity", "PSU"),
            ("ocean", "currentSpeed", "m/s"),
            ("ocean", "currentDirection", "°"),
            ("waves", "waveHeight", "m"),
            ("waves", "wavePeriod", "s"),
            ("waves", "waveDirection", "°"),
            # Expanded parameters
            ("meteorology", "shortWaveRadiation", "W/m²"),
            ("meteorology", "longWaveRadiation", "W/m²"),
            ("meteorology", "windGust", "m/s"),
            ("waves", "swellHeight", "m"),
            ("waves", "swellPeriod", "s"),
            ("waves", "swellDirection", "°"),
            ("waves", "windWaveHeight", "m"),
            ("waves", "windWavePeriod", "s"),
            ("ocean", "conductivity", "S/m"),
        ]

        def _extract(group, key, unit):
            m = event["telemetry"].get(group, {}).get(key, {})
            if not m:
                return None
            if m.get("unit") == unit or (unit == "PSU" and m.get("unit") in ("psu", "PSU")):
                return m.get("value")
            return None

        values = [_extract(g, k, u) for g, k, u in expected]

        await self.pool.execute("""INSERT INTO buoy_observations
            (event_id, buoy_id, observation_timestamp, received_timestamp, source,
             wind_speed, wind_direction, air_temperature, pressure, humidity, rainfall,
             sst, salinity, current_speed, current_direction,
             wave_height, wave_period, wave_direction,
             shortwave_radiation, longwave_radiation, wind_gust,
             swell_height, swell_period, swell_direction,
             wind_wave_height, wind_wave_period,
             conductivity,
             raw_payload, latitude, longitude)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,
                    $19,$20,$21,$22,$23,$24,$25,$26,$27,$28::jsonb,$29,$30)
            ON CONFLICT (event_id) DO NOTHING""",
            event["eventId"], event["buoyId"],
            datetime.fromisoformat(event["timestamp"]),
            datetime.fromisoformat(event["receivedAt"]),
            event["source"],
            *values,
            json.dumps(event),
            event.get("location", {}).get("latitude"),
            event.get("location", {}).get("longitude"))
        log.info("[POSTGRES] Stored %s observation", event["buoyId"])

    async def history(self, buoy_id, start, end, limit):
        await self.connect()
        rows = await self.pool.fetch("""SELECT raw_payload FROM buoy_observations
            WHERE buoy_id=$1 AND observation_timestamp BETWEEN $2 AND $3
            ORDER BY observation_timestamp DESC LIMIT $4""",buoy_id,start,end,limit)
        return [json.loads(row["raw_payload"]) for row in reversed(rows)]

    async def close(self):
        if self.pool: await self.pool.close()
