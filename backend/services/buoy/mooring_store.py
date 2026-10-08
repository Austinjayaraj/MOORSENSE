"""Mooring configuration persistence and estimate storage."""
import json
import logging
from pathlib import Path
import asyncpg

log = logging.getLogger(__name__)


class MooringStore:
    def __init__(self, pool_provider):
        self._pool_provider = pool_provider

    async def _pool(self):
        store = self._pool_provider
        await store.connect()
        return store.pool

    async def ensure_schema(self):
        pool = await self._pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(67490232)")
                await conn.execute(Path(__file__).parents[2].joinpath(
                    "migrations/002_mooring_configuration.sql").read_text())

    async def get_config(self, buoy_id: str) -> dict | None:
        pool = await self._pool()
        row = await pool.fetchrow(
            "SELECT * FROM mooring_configurations WHERE buoy_id=$1 ORDER BY updated_at DESC LIMIT 1",
            buoy_id)
        if not row:
            return None
        config = dict(row)
        segments = await pool.fetch(
            "SELECT * FROM mooring_line_segments WHERE configuration_id=$1 ORDER BY line_id, segment",
            config["id"])
        config["line_segments"] = [dict(s) for s in segments]
        return config

    async def save_estimate(self, estimate: dict):
        pool = await self._pool()
        await pool.execute("""INSERT INTO mooring_estimates
            (event_id, buoy_id, source_observation_timestamp, calculated_at,
             environmental_forces, lines, max_tension_N, max_utilization,
             risk_level, model_status, raw_payload)
            VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7,$8,$9,$10,$11::jsonb)
            ON CONFLICT (event_id) DO NOTHING""",
            estimate["event_id"], estimate["buoy_id"],
            estimate["source_observation_timestamp"], estimate["calculated_at"],
            json.dumps(estimate.get("environmental_forces", {})),
            json.dumps(estimate.get("lines", [])),
            estimate.get("max_tension_N"), estimate.get("max_utilization"),
            estimate.get("risk_level"), estimate["model_status"],
            json.dumps(estimate))
