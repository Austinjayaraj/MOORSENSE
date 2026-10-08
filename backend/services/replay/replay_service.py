"""Replay service: orchestrates run registry, determinism, and persistence.

A replay run is deterministic: same (station, time range, model_version,
physics_version) always produces the same results.

Determinism hash covers: station_id + start_time + end_time + model_version +
physics_version. Does NOT include created_at or run_id.
"""
from __future__ import annotations
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.mooring.config_resolver import MooringConfigResolver
from services.mooring.versioned_config import model_version_metadata
from .replay_runner import ReplayObservation, ReplayResult, ReplayRunner
from .replay_store import ReplayStore

log = logging.getLogger(__name__)


def _determinism_hash(station_id: str, start_time: str, end_time: str,
                       model_version: str, physics_version: str) -> str:
    payload = f"{station_id}|{start_time}|{end_time}|{model_version}|{physics_version}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class ReplayService:
    """Orchestrates replay: registry + runner + persistence."""

    def __init__(self, pool_provider, resolver: MooringConfigResolver | None = None):
        self.store = ReplayStore(pool_provider)
        self.runner = ReplayRunner(resolver or MooringConfigResolver())

    async def run_replay(self, station_id: str,
                         start_time: datetime, end_time: datetime,
                         observations: list[ReplayObservation]) -> dict:
        """Run a replay, persist results, and return run metadata.

        Raises if PostgreSQL is unavailable — never silently falls back.
        """
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("start_time and end_time must be timezone-aware")
        if start_time >= end_time:
            raise ValueError("start_time must be before end_time")

        versions = model_version_metadata()
        run_id = str(uuid.uuid4())
        input_hash = _determinism_hash(
            station_id,
            start_time.isoformat(),
            end_time.isoformat(),
            versions["model_version"],
            versions["physics_version"],
        )

        pool = await self.store._pool()  # raises if DB unavailable
        await pool.execute("""
            INSERT INTO mooring_replay_runs
              (run_id, station_id, start_time, end_time, status,
               observation_count, model_version, physics_version,
               configuration_version, input_hash)
            VALUES ($1,$2,$3,$4,'RUNNING',$5,$6,$7,$8,$9)
        """, run_id, station_id, start_time, end_time,
            len(observations), versions["model_version"],
            versions["physics_version"], versions["configuration_version"],
            input_hash)

        results = self.runner.replay_observations(station_id, observations)
        success_count = 0
        failure_count = 0
        errors = []

        for r in results:
            try:
                await self.store.save(r, run_id=run_id)
                success_count += 1
            except Exception as exc:
                failure_count += 1
                errors.append(str(exc)[:120])

        status = "COMPLETED" if failure_count == 0 else (
            "PARTIAL" if success_count > 0 else "FAILED")

        await pool.execute("""
            UPDATE mooring_replay_runs
            SET status=$1, completed_at=$2,
                success_count=$3, failure_count=$4, error_summary=$5
            WHERE run_id=$6
        """, status, datetime.now(timezone.utc),
            success_count, failure_count,
            "; ".join(errors[:3]) if errors else None,
            run_id)

        return {
            "run_id": run_id,
            "station_id": station_id,
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "observation_count": len(observations),
            "successful_count": success_count,
            "failed_count": failure_count,
            "status": status,
            "model_version": versions["model_version"],
            "physics_version": versions["physics_version"],
            "input_hash": input_hash,
        }

    async def get_run(self, run_id: str) -> dict | None:
        pool = await self.store._pool()
        row = await pool.fetchrow(
            "SELECT * FROM mooring_replay_runs WHERE run_id=$1", run_id)
        return dict(row) if row else None

    async def get_results(self, run_id: str, limit: int = 200) -> list[dict]:
        pool = await self.store._pool()
        rows = await pool.fetch("""
            SELECT observation_timestamp, estimated_tension_n, estimated_line_angle_deg,
                   wind_speed, current_speed, wave_height,
                   forcing_mode, confidence, solver_status, overall_risk_status,
                   wind_force_n, current_force_n, wave_force_n, total_known_force_n
            FROM mooring_replay_results
            WHERE run_id=$1
            ORDER BY observation_timestamp
            LIMIT $2
        """, run_id, limit)
        return [dict(r) for r in rows]

    async def get_summary(self, run_id: str) -> dict:
        pool = await self.store._pool()
        run = await pool.fetchrow(
            "SELECT * FROM mooring_replay_runs WHERE run_id=$1", run_id)
        if not run:
            return {"error": "Run not found"}

        stats = await pool.fetchrow("""
            SELECT
              MAX(estimated_tension_n)   AS max_tension_n,
              MAX(estimated_line_angle_deg) AS max_angle_deg,
              MAX(wind_speed)            AS max_wind_speed,
              COUNT(*)                   AS result_count,
              COUNT(CASE WHEN solver_status='CONVERGED' THEN 1 END) AS converged_count
            FROM mooring_replay_results
            WHERE run_id=$1
        """, run_id)

        return {
            "run_id": run_id,
            "station_id": run["station_id"],
            "status": run["status"],
            "observation_count": run["observation_count"],
            "success_count": run["success_count"],
            "result_count": stats["result_count"] if stats else 0,
            "converged_count": stats["converged_count"] if stats else 0,
            "max_tension_n": stats["max_tension_n"] if stats else None,
            "max_line_angle_deg": stats["max_angle_deg"] if stats else None,
            "max_wind_speed": stats["max_wind_speed"] if stats else None,
            "model_version": run["model_version"],
            "physics_version": run["physics_version"],
            "input_hash": run["input_hash"],
        }
