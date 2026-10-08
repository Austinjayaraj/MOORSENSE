"""Mooring response pipeline — orchestrates config resolution, force calculation,
catenary solution, risk assessment, and confidence calculation for a single buoy.
"""
import logging
from datetime import datetime, timezone

from .models import (
    MooringConfiguration, MooringResponse, EnvironmentalState,
    FleetDigitalTwinEntry,
)
from .config_resolver import MooringConfigResolver
from .environmental_forces import compute_environmental_forces
from .catenary_solver import solve_catenary, compute_utilization, compute_safety_factor
from .risk_engine import assess_risk
from .confidence import compute_confidence
from .buoy_equilibrium import solve_equilibrium

log = logging.getLogger(__name__)


def extract_environmental_state(telemetry: dict) -> EnvironmentalState:
    """Extract environmental state from the normalized telemetry dict."""
    met = telemetry.get("meteorology", {})
    ocean = telemetry.get("ocean", {})
    waves = telemetry.get("waves", {})
    profiles = telemetry.get("profiles", {})

    def val(group, key):
        m = group.get(key)
        if isinstance(m, dict):
            v = m.get("value")
            return float(v) if v is not None else None
        return None

    # Build current profile from depth measurements
    current_profile = None
    if "current" in profiles:
        pts = profiles["current"]
        if isinstance(pts, list) and pts:
            current_profile = [{"depth": p.get("depth", 0), "speed": p.get("value")}
                               for p in pts if p.get("value") is not None]

    sources = {}
    if val(met, "windSpeed") is not None:
        sources["wind"] = "MEASURED"
    if val(ocean, "currentSpeed") is not None:
        sources["current"] = "MEASURED"
    else:
        sources["current"] = "UNAVAILABLE"
    if val(waves, "waveHeight") is not None:
        sources["wave"] = "MEASURED"
    else:
        sources["wave"] = "UNAVAILABLE"

    return EnvironmentalState(
        wind_speed_ms=val(met, "windSpeed"),
        wind_direction_deg=val(met, "windDirection"),
        current_speed_ms=val(ocean, "currentSpeed"),
        current_direction_deg=val(ocean, "currentDirection"),
        wave_height_m=val(waves, "waveHeight"),
        wave_period_s=val(waves, "wavePeriod"),
        wave_direction_deg=val(waves, "waveDirection"),
        current_profile=current_profile,
        sources=sources,
    )


def compute_mooring_response(buoy_id: str,
                             latitude: float,
                             longitude: float,
                             telemetry: dict,
                             observation_timestamp: str,
                             resolver: MooringConfigResolver,
                             authoritative_config: dict | None = None,
                             telemetry_age_seconds: float | None = None) -> MooringResponse:
    """Run the full mooring Digital Twin pipeline for a single buoy."""
    model_ts = datetime.now(timezone.utc).isoformat()

    # 1. Resolve mooring configuration
    config = resolver.resolve(buoy_id, latitude, longitude, authoritative_config)

    # 2. Extract environmental state
    env = extract_environmental_state(telemetry)

    # 3. Check if we can proceed
    if not config.has_minimum_geometry():
        overall_conf, conf_breakdown = compute_confidence(config, env, "NOT_RUN", telemetry_age_seconds)
        return MooringResponse(
            buoy_id=buoy_id,
            observation_timestamp=observation_timestamp,
            model_timestamp=model_ts,
            risk_state="INSUFFICIENT_DATA",
            confidence=overall_conf,
            confidence_breakdown=conf_breakdown,
            solver_status="NOT_RUN",
            forcing_mode="UNKNOWN",
            environmental_completeness="UNKNOWN",
            configuration_version=config.configuration_version,
        )

    # 4. Compute environmental forces
    forces = compute_environmental_forces(env, config)

    # 5. Solve catenary (direct force→tension)
    h_force = forces.total_horizontal_n or 0.0
    solution = solve_catenary(config, h_force)
    solver_status = "CONVERGED" if solution.converged else "WARNING" if solution.iterations > 0 else "FAILED"

    # 5b. Coupled equilibrium (predicted buoy offset) — best-effort, non-blocking
    equilibrium = None
    try:
        equilibrium = solve_equilibrium(config, forces)
    except Exception:
        pass

    # 6. Utilization and safety factor
    utilization = compute_utilization(solution.fairlead_tension_n, config.segments) if solution.converged else None
    safety_factor = compute_safety_factor(solution.fairlead_tension_n, config.segments) if solution.converged else None

    # 7. Risk assessment
    risk = assess_risk(
        utilization=utilization,
        safety_factor=safety_factor,
        excursion_m=solution.fairlead_excursion_m if solution.converged else None,
        solver_converged=solution.converged)

    # 8. Forcing mode classification
    has_wind = env.wind_speed_ms is not None
    has_current = env.current_speed_ms is not None
    has_waves = env.wave_height_m is not None
    if has_wind and has_current and has_waves:
        forcing_mode = "WIND_CURRENT_WAVE"
        env_completeness = "FULL"
    elif has_wind and has_current:
        forcing_mode = "WIND_CURRENT"
        env_completeness = "PARTIAL_NO_WAVES"
    elif has_wind and has_waves:
        forcing_mode = "WIND_WAVE"
        env_completeness = "PARTIAL_NO_CURRENT"
    elif has_wind:
        forcing_mode = "WIND_ONLY"
        env_completeness = "PARTIAL_WIND_ONLY"
    else:
        forcing_mode = "NO_FORCING"
        env_completeness = "NONE"

    # 9. Confidence
    overall_conf, conf_breakdown = compute_confidence(config, env, solver_status, telemetry_age_seconds)

    response = MooringResponse(
        buoy_id=buoy_id,
        observation_timestamp=observation_timestamp,
        model_timestamp=model_ts,
        fairlead_tension_n=solution.fairlead_tension_n if solution.converged else None,
        anchor_tension_n=solution.anchor_tension_n if solution.converged else None,
        horizontal_tension_n=solution.horizontal_tension_n if solution.converged else None,
        vertical_tension_n=solution.vertical_tension_n if solution.converged else None,
        line_angle_deg=solution.line_angle_deg if solution.converged else None,
        horizontal_excursion_m=solution.fairlead_excursion_m if solution.converged else None,
        utilization=utilization,
        safety_factor=safety_factor,
        environmental_forces=forces,
        confidence_breakdown=conf_breakdown,
        risk_state=risk,
        confidence=overall_conf,
        solver_status=solver_status,
        solver_iterations=solution.iterations,
        solver_residual=round(solution.residual, 6) if solution.residual != float('inf') else None,
        forcing_mode=forcing_mode,
        environmental_completeness=env_completeness,
        configuration_version=config.configuration_version,
        predicted_offset_m=equilibrium.predicted_offset_m if equilibrium else None,
        predicted_bearing_deg=equilibrium.predicted_bearing_deg if equilibrium else None,
        equilibrium_residual_n=equilibrium.force_residual_magnitude_n if equilibrium else None,
        equilibrium_solver_status=equilibrium.solver_status if equilibrium else None,
    )

    log.info("[MOORING] %s tension=%.1fkN angle=%.1f° util=%.3f risk=%s conf=%s solver=%s(%d) forcing=%s",
             buoy_id,
             (solution.fairlead_tension_n or 0) / 1000,
             solution.line_angle_deg or 0,
             utilization or 0, risk, overall_conf,
             solver_status, solution.iterations, forcing_mode)

    return response
