"""Dataset builder for mooring Digital Twin ML experiments.

POLICY:
- No random train/test splits for time series — chronological only.
- No supervised tension target until physical measurements exist.
- Features retain station_id, timestamp, and provenance metadata.
- Future-data leakage is prevented by design.

Current supervised target status: UNAVAILABLE
(No physical tension, line angle, or validated displacement measurements.)

Available target: anomaly detection (unsupervised only) until physical
measurements are obtained.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

SUPERVISED_TARGET_STATUS = "UNAVAILABLE"
SUPERVISED_TARGET_NOTES = (
    "No physical tension measurements, validated line angles, or "
    "surveyed displacement records exist. Supervised tension prediction "
    "cannot be trained without fabricating labels."
)


@dataclass
class DatasetRow:
    """One row in the ML dataset, retaining full provenance."""
    station_id: str
    timestamp: datetime
    model_version: str
    configuration_version: str
    # Environmental features (None = unavailable, never 0-substituted)
    wind_speed: float | None = None
    wind_direction: float | None = None
    current_speed: float | None = None
    wave_height: float | None = None
    wave_period: float | None = None
    # Physics-derived features (None = solver did not converge / config unavailable)
    estimated_tension_n: float | None = None
    estimated_line_angle_deg: float | None = None
    horizontal_excursion_m: float | None = None
    wind_force_n: float | None = None
    current_force_n: float | None = None
    wave_force_n: float | None = None
    # Data quality features
    forcing_mode: str = "UNKNOWN"
    environmental_completeness: str = "UNKNOWN"
    confidence: str = "UNKNOWN"
    solver_status: str = "NOT_RUN"
    # Target (None = no physical measurement; never substitute with model output)
    measured_tension_n: float | None = None
    validated: bool = False


@dataclass
class MLDataset:
    rows: list[DatasetRow] = field(default_factory=list)
    station_ids: list[str] = field(default_factory=list)
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    supervised_target_status: str = SUPERVISED_TARGET_STATUS
    notes: str = SUPERVISED_TARGET_NOTES

    def has_supervised_target(self) -> bool:
        return any(r.measured_tension_n is not None and r.validated for r in self.rows)

    def feature_matrix(self, include_physics: bool = True) -> list[dict]:
        """Return feature dicts. None values preserved — not filled with zeros."""
        features = []
        for r in self.rows:
            row = {
                "station_id": r.station_id,
                "timestamp": r.timestamp.isoformat(),
                "wind_speed": r.wind_speed,
                "wind_direction": r.wind_direction,
                "current_speed": r.current_speed,
                "wave_height": r.wave_height,
                "wave_period": r.wave_period,
                "forcing_mode": r.forcing_mode,
                "confidence": r.confidence,
            }
            if include_physics:
                row.update({
                    "estimated_tension_n": r.estimated_tension_n,
                    "estimated_line_angle_deg": r.estimated_line_angle_deg,
                    "horizontal_excursion_m": r.horizontal_excursion_m,
                    "wind_force_n": r.wind_force_n,
                })
            features.append(row)
        return features


def build_from_replay_results(replay_results: list) -> MLDataset:
    """Build a dataset from replay results.

    Does NOT add supervised targets — those require physical measurements.
    """
    rows = []
    stations = set()
    timestamps = []
    for r in replay_results:
        rr = r.mooring_response
        ef = rr.environmental_forces
        obs_ts = datetime.fromisoformat(r.observation_timestamp)
        stations.add(r.station_id)
        timestamps.append(obs_ts)
        telemetry = r.telemetry_snapshot

        def _tv(group, key):
            m = telemetry.get(group, {}).get(key)
            return m.get("value") if isinstance(m, dict) else None

        rows.append(DatasetRow(
            station_id=r.station_id,
            timestamp=obs_ts,
            model_version=r.model_versions.get("model_version", ""),
            configuration_version=r.model_versions.get("configuration_version", ""),
            wind_speed=_tv("meteorology", "windSpeed"),
            wind_direction=_tv("meteorology", "windDirection"),
            current_speed=_tv("ocean", "currentSpeed"),
            wave_height=_tv("waves", "waveHeight"),
            wave_period=_tv("waves", "wavePeriod"),
            estimated_tension_n=rr.fairlead_tension_n,
            estimated_line_angle_deg=rr.line_angle_deg,
            horizontal_excursion_m=rr.horizontal_excursion_m,
            wind_force_n=ef.wind_force_n if ef else None,
            current_force_n=ef.current_force_n if ef else None,
            wave_force_n=ef.wave_force_n if ef else None,
            forcing_mode=rr.forcing_mode,
            environmental_completeness=rr.environmental_completeness,
            confidence=rr.confidence,
            solver_status=rr.solver_status,
        ))

    return MLDataset(
        rows=rows,
        station_ids=sorted(stations),
        time_range_start=min(timestamps) if timestamps else None,
        time_range_end=max(timestamps) if timestamps else None,
    )
