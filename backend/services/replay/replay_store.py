"""PostgreSQL persistence for mooring replay results.

Uses ON CONFLICT DO NOTHING so the same (station, timestamp, model, physics)
combination is idempotent — re-running a replay never overwrites prior results.
Different model versions coexist in the table.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from .replay_runner import ReplayResult

log = logging.getLogger(__name__)


class ReplayStore:
    def __init__(self, pool_provider):
        self._pool_provider = pool_provider

    async def _pool(self):
        store = self._pool_provider
        await store.connect()
        return store.pool

    async def save(self, result: ReplayResult, run_id: str | None = None) -> bool:
        """Persist one replay result. Returns True if inserted, False if duplicate."""
        pool = await self._pool()
        r = result.mooring_response
        ef = r.environmental_forces

        def _env(attr):
            return getattr(ef, attr, None) if ef else None

        raw = {
            "mooring_response": r.model_dump(mode="json"),
            "telemetry_snapshot": result.telemetry_snapshot,
            "model_versions": result.model_versions,
        }
        provenance = {
            "configuration_version": r.configuration_version,
            "model_version": r.model_version,
            "physics_version": r.physics_version,
            "forcing_mode": r.forcing_mode,
        }

        env_inputs = result.telemetry_snapshot.get("meteorology", {})

        def _tv(group, key):
            m = result.telemetry_snapshot.get(group, {}).get(key)
            return m.get("value") if isinstance(m, dict) else None

        row = await pool.fetchrow("""
            INSERT INTO mooring_replay_results (
                station_id, observation_timestamp,
                configuration_version, model_version, physics_version, environment_version,
                wind_speed, wind_direction, current_speed, current_direction,
                wave_height, wave_period, wave_direction,
                wind_force_n, current_force_n, wave_force_n, total_known_force_n,
                estimated_tension_n, estimated_line_angle_deg,
                estimated_anchor_load_n, horizontal_excursion_m,
                data_risk, model_risk, mooring_risk, overall_risk_status,
                confidence, environmental_completeness, forcing_mode, solver_status,
                provenance_json, raw_result_json, run_id
            ) VALUES (
                $1,$2,$3,$4,$5,$6,
                $7,$8,$9,$10,$11,$12,$13,
                $14,$15,$16,$17,
                $18,$19,$20,$21,
                $22,$23,$24,$25,$26,$27,$28,$29,
                $30::jsonb,$31::jsonb,$32
            )
            ON CONFLICT (station_id, observation_timestamp, model_version, physics_version)
            DO NOTHING
            RETURNING id
        """,
            result.station_id,
            datetime.fromisoformat(result.observation_timestamp),
            r.configuration_version,
            r.model_version,
            r.physics_version,
            result.model_versions.get("environment_version"),
            _tv("meteorology", "windSpeed"),
            _tv("meteorology", "windDirection"),
            _tv("ocean", "currentSpeed"),
            _tv("ocean", "currentDirection"),
            _tv("waves", "waveHeight"),
            _tv("waves", "wavePeriod"),
            _tv("waves", "waveDirection"),
            _env("wind_force_n"),
            _env("current_force_n"),
            _env("wave_force_n"),
            _env("total_horizontal_n"),
            r.fairlead_tension_n,
            r.line_angle_deg,
            r.anchor_tension_n,
            r.horizontal_excursion_m,
            None,  # data_risk — from separated risk if computed
            None,  # model_risk
            r.risk_state,
            r.risk_state,
            r.confidence,
            r.environmental_completeness,
            r.forcing_mode,
            r.solver_status,
            json.dumps(provenance),
            json.dumps(raw),
            run_id,
        )
        inserted = row is not None
        log.debug("[REPLAY_STORE] %s %s %s", result.station_id,
                  result.observation_timestamp, "inserted" if inserted else "duplicate")
        return inserted

    async def query(self, station_id: str, start: datetime, end: datetime,
                    limit: int = 120) -> list[dict]:
        pool = await self._pool()
        rows = await pool.fetch("""
            SELECT raw_result_json, observation_timestamp, confidence,
                   forcing_mode, solver_status, estimated_tension_n,
                   estimated_line_angle_deg, overall_risk_status, model_version
            FROM mooring_replay_results
            WHERE station_id = $1
              AND observation_timestamp BETWEEN $2 AND $3
            ORDER BY observation_timestamp
            LIMIT $4
        """, station_id, start, end, limit)
        return [dict(r) for r in rows]
