"""Fleet-wide Digital Twin runner.

Iterates all accessible OMNI buoys and computes mooring response for each.
One buoy failure must not crash the fleet. Results are collected for the
fleet summary API and individual persistence.
"""
import logging
from datetime import datetime, timezone

from .models import FleetDigitalTwinEntry, MooringResponse
from .config_resolver import MooringConfigResolver
from .mooring_response import compute_mooring_response, extract_environmental_state

log = logging.getLogger(__name__)


class FleetRunner:
    def __init__(self, resolver: MooringConfigResolver | None = None):
        self.resolver = resolver or MooringConfigResolver()
        self.latest_responses: dict[str, MooringResponse] = {}
        self.latest_configs: dict[str, object] = {}

    def run_fleet(self, buoys: dict, cache) -> list[FleetDigitalTwinEntry]:
        """Run the Digital Twin for every buoy in the catalog.

        Args:
            buoys: dict of buoy_id -> Buoy model (from BuoyRuntime.buoys)
            cache: BuoyCache with latest observations
        """
        results = []
        for buoy_id, buoy in buoys.items():
            try:
                entry = self._run_single(buoy_id, buoy, cache)
                results.append(entry)
            except Exception as exc:
                log.warning("[FLEET] %s failed: %s", buoy_id, type(exc).__name__)
                results.append(FleetDigitalTwinEntry(
                    buoy_id=buoy_id, error=f"{type(exc).__name__}: {exc}"))
        return results

    def _run_single(self, buoy_id: str, buoy, cache) -> FleetDigitalTwinEntry:
        obs = cache.latest.get(buoy_id)
        if obs is None:
            return FleetDigitalTwinEntry(buoy_id=buoy_id, error="No observation available")

        telemetry = obs.telemetry.model_dump(mode="json") if obs.telemetry else {}
        obs_ts = obs.timestamp.isoformat()
        age = (datetime.now(timezone.utc) - obs.timestamp).total_seconds()

        response = compute_mooring_response(
            buoy_id=buoy_id,
            latitude=buoy.latitude,
            longitude=buoy.longitude,
            telemetry=telemetry,
            observation_timestamp=obs_ts,
            resolver=self.resolver,
            telemetry_age_seconds=age,
        )

        self.latest_responses[buoy_id] = response
        config = self.resolver.resolve(buoy_id, buoy.latitude, buoy.longitude)
        self.latest_configs[buoy_id] = config

        return FleetDigitalTwinEntry(
            buoy_id=buoy_id,
            tension_kn=round(response.fairlead_tension_n / 1000, 2) if response.fairlead_tension_n else None,
            angle_deg=response.line_angle_deg,
            utilization=response.utilization,
            safety_factor=response.safety_factor,
            risk=response.risk_state,
            confidence=response.confidence,
            observation_timestamp=obs_ts,
            solver_status=response.solver_status,
        )

    def get_response(self, buoy_id: str) -> MooringResponse | None:
        return self.latest_responses.get(buoy_id)

    def get_config(self, buoy_id: str):
        return self.latest_configs.get(buoy_id)
