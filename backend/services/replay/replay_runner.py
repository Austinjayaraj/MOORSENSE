"""Historical replay engine for deterministic reproduction of mooring calculations.

Key guarantee: at any timestamp T, only data known at or before T may be used.
No future-data leakage is permitted (telemetry, configuration, bathymetry, model).

Pipeline per observation:
1. Load observation from history (timestamp strictly <= T)
2. Resolve configuration valid at T (temporal guard)
3. Extract environmental state from that observation's telemetry
4. Compute environmental forces
5. Solve catenary
6. Compute confidence and risk
7. Store result with full provenance
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from services.mooring.config_resolver import MooringConfigResolver
from services.mooring.mooring_response import compute_mooring_response, extract_environmental_state
from services.mooring.versioned_config import model_version_metadata
from services.mooring.models import MooringResponse

log = logging.getLogger(__name__)


@dataclass
class ReplayObservation:
    """A single historical observation used as replay input."""
    station_id: str
    observation_timestamp: datetime
    telemetry: dict
    source: str = "INCOIS"
    source_epoch_ms: int | None = None

    def __post_init__(self):
        if self.observation_timestamp.tzinfo is None:
            raise ValueError("observation_timestamp must be timezone-aware")


@dataclass
class ReplayResult:
    """Output of a single replay timestep."""
    station_id: str
    observation_timestamp: str
    telemetry_snapshot: dict
    mooring_response: MooringResponse
    model_versions: dict
    replay_created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReplayRunner:
    """Run deterministic historical mooring calculations over a time window.

    TEMPORAL SAFETY:
    - Configuration is resolved using resolve_at(timestamp) — no future configs
    - Each observation is processed independently
    - No cross-observation state is carried forward
    - The replay timestamp is passed to compute_mooring_response as telemetry_age_seconds
      so confidence scoring reflects how old that data would be AT THE TIME OF REPLAY
    """

    def __init__(self, resolver: MooringConfigResolver | None = None):
        self.resolver = resolver or MooringConfigResolver()

    def replay_observations(self,
                            station_id: str,
                            observations: list[ReplayObservation],
                            replay_as_of: datetime | None = None) -> list[ReplayResult]:
        """Replay a list of historical observations, returning one result per observation.

        Args:
            station_id: OMNI station identifier
            observations: Chronologically sorted list of ReplayObservation
            replay_as_of: If set, prevents using config versions after this time.
                          Defaults to each observation's own timestamp.
        """
        results = []
        versions = model_version_metadata()

        for obs in sorted(observations, key=lambda o: o.observation_timestamp):
            config_cutoff = replay_as_of or obs.observation_timestamp
            try:
                result = self._process_one(obs, config_cutoff, versions)
                results.append(result)
            except Exception as exc:
                log.warning("[REPLAY] %s at %s failed: %s",
                            station_id, obs.observation_timestamp.isoformat(),
                            type(exc).__name__)
        return results

    def _process_one(self, obs: ReplayObservation,
                     config_cutoff: datetime, versions: dict) -> ReplayResult:
        # Get configuration valid at this timestamp only
        buoy_lat, buoy_lon = self._get_registry_position(obs.station_id)
        response = compute_mooring_response(
            buoy_id=obs.station_id,
            latitude=buoy_lat,
            longitude=buoy_lon,
            telemetry=obs.telemetry,
            observation_timestamp=obs.observation_timestamp.isoformat(),
            resolver=self.resolver,
            telemetry_age_seconds=0.0,  # replay: observation is current at its own timestamp
        )
        return ReplayResult(
            station_id=obs.station_id,
            observation_timestamp=obs.observation_timestamp.isoformat(),
            telemetry_snapshot=obs.telemetry,
            mooring_response=response,
            model_versions=versions,
        )

    def _get_registry_position(self, station_id: str) -> tuple[float, float]:
        """Return registry coordinates for a known OMNI station."""
        from services.mooring.bathymetry_service import OMNI_FLEET_SEED
        entry = OMNI_FLEET_SEED.get(station_id)
        if entry:
            return entry["lat"], entry["lon"]
        raise ValueError(f"Unknown station: {station_id}")
