"""Environmental force calculations and quasi-static catenary mooring solver.

Wind and current drag use standard quadratic drag formulas.
Wave forcing uses a documented simplified Morison-type estimate clearly
labeled as screening-level. No result is labeled engineering-grade unless
a validated hydrodynamic model is implemented.
"""
import math
from .mooring_models import (
    MooringConfiguration, EnvironmentalForces, LineTensionResult, MooringEstimate,
)

RHO_AIR = 1.225
RHO_WATER = 1025.0
GRAVITY = 9.81
CD_WIND = 1.2
CD_CURRENT = 1.0


def wind_force(speed_ms: float | None, projected_area_m2: float | None,
               cd: float = CD_WIND) -> float | None:
    if speed_ms is None or projected_area_m2 is None:
        return None
    return 0.5 * RHO_AIR * cd * projected_area_m2 * speed_ms ** 2


def current_force(speed_ms: float | None, submerged_area_m2: float | None,
                  cd: float = CD_CURRENT) -> float | None:
    if speed_ms is None or submerged_area_m2 is None:
        return None
    return 0.5 * RHO_WATER * cd * submerged_area_m2 * speed_ms ** 2


def wave_force_screening(wave_height_m: float | None, wave_period_s: float | None,
                         buoy_width_m: float | None, draft_m: float | None) -> float | None:
    """Simplified Morison-type inertia estimate for screening only.

    Uses F ~ 0.5 * rho * Cd * D * Hs^2 / (2*T^2) * pi^2 * draft
    This is an order-of-magnitude screening estimate, NOT a validated
    hydrodynamic computation. model_level = "screening".
    """
    if any(v is None for v in (wave_height_m, wave_period_s, buoy_width_m, draft_m)):
        return None
    if wave_period_s <= 0:
        return None
    cd_wave = 1.0
    particle_velocity = math.pi * wave_height_m / wave_period_s
    return 0.5 * RHO_WATER * cd_wave * buoy_width_m * draft_m * particle_velocity ** 2


def resolve_forces(wind_f: float | None, wind_dir: float | None,
                   current_f: float | None, current_dir: float | None,
                   wave_f: float | None, wave_dir: float | None) -> tuple[float | None, float | None]:
    """Resolve all horizontal forces into a resultant magnitude and direction."""
    fx, fy = 0.0, 0.0
    has_any = False
    for force, direction in [(wind_f, wind_dir), (current_f, current_dir), (wave_f, wave_dir)]:
        if force is not None and direction is not None:
            rad = math.radians(direction)
            fx += force * math.sin(rad)
            fy += force * math.cos(rad)
            has_any = True
    if not has_any:
        return None, None
    magnitude = math.sqrt(fx ** 2 + fy ** 2)
    direction_deg = math.degrees(math.atan2(fx, fy)) % 360
    return magnitude, direction_deg


def compute_environmental_forces(telemetry: dict, config: MooringConfiguration) -> EnvironmentalForces:
    met = telemetry.get("meteorology", {})
    ocean = telemetry.get("ocean", {})
    waves = telemetry.get("waves", {})

    wind_speed = _metric_value(met, "windSpeed")
    wind_dir = _metric_value(met, "windDirection")
    current_speed = _metric_value(ocean, "currentSpeed")
    current_dir = _metric_value(ocean, "currentDirection")
    wave_height = _metric_value(waves, "waveHeight")
    wave_period = _metric_value(waves, "wavePeriod")
    wave_dir = _metric_value(waves, "waveDirection")

    projected = config.projected_area_m2
    draft = config.buoy_height_m * 0.5 if config.buoy_height_m else None
    submerged_area = (config.buoy_width_m or 0) * (draft or 0) if config.buoy_width_m and draft else None

    f_wind = wind_force(wind_speed, projected)
    f_current = current_force(current_speed, submerged_area)
    f_wave = wave_force_screening(wave_height, wave_period, config.buoy_width_m, draft)

    total_h, total_dir = resolve_forces(f_wind, wind_dir, f_current, current_dir, f_wave, wave_dir)

    return EnvironmentalForces(
        wind_force_N=round(f_wind, 2) if f_wind is not None else None,
        wind_direction_deg=wind_dir,
        current_force_N=round(f_current, 2) if f_current is not None else None,
        current_direction_deg=current_dir,
        wave_force_N=round(f_wave, 2) if f_wave is not None else None,
        wave_direction_deg=wave_dir,
        total_horizontal_force_N=round(total_h, 2) if total_h is not None else None,
        total_force_direction_deg=round(total_dir, 2) if total_dir is not None else None,
        model_level="screening",
        inputs_used={
            "wind_speed_ms": wind_speed, "current_speed_ms": current_speed,
            "wave_height_m": wave_height, "wave_period_s": wave_period,
            "projected_area_m2": projected, "submerged_area_m2": submerged_area,
        }
    )


def catenary_tension(horizontal_force_N: float, water_depth_m: float,
                     line_length_m: float, weight_per_m: float,
                     pretension_N: float = 0.0,
                     seabed_friction: float = 0.0) -> dict:
    """Quasi-static catenary mooring solution for a single line.

    Solves the classic catenary equation for a mooring line:
    - Determines seabed contact length
    - Computes horizontal and vertical tension at fairlead
    - Accounts for pretension and seabed friction
    """
    if water_depth_m <= 0 or line_length_m <= 0 or weight_per_m <= 0:
        return {"error": "Invalid line parameters"}

    w = weight_per_m * GRAVITY
    H = max(horizontal_force_N + pretension_N, 1.0)

    # Catenary parameter
    a = H / w

    # Suspended line length from catenary: s = a * sinh(x/a), depth: z = a*(cosh(x/a) - 1)
    # At fairlead: depth = water_depth_m
    # Solve for suspended length: s = sqrt(water_depth^2 + 2*a*water_depth)
    suspended_length = math.sqrt(water_depth_m ** 2 + 2 * a * water_depth_m)

    if suspended_length > line_length_m:
        suspended_length = line_length_m

    grounded_length = max(0.0, line_length_m - suspended_length)

    # Friction force from grounded portion
    friction_force = seabed_friction * w * grounded_length

    H_effective = H + friction_force

    # Vertical tension at fairlead
    V = w * suspended_length

    # Resultant tension
    T = math.sqrt(H_effective ** 2 + V ** 2)

    # Line angle at fairlead (from horizontal)
    angle_rad = math.atan2(V, H_effective)
    angle_deg = math.degrees(angle_rad)

    return {
        "horizontal_tension_N": round(H_effective, 2),
        "vertical_tension_N": round(V, 2),
        "resultant_tension_N": round(T, 2),
        "line_angle_deg": round(angle_deg, 2),
        "suspended_length_m": round(suspended_length, 2),
        "grounded_length_m": round(grounded_length, 2),
        "catenary_parameter_m": round(a, 2),
    }


def compute_line_tensions(env_forces: EnvironmentalForces,
                          config: MooringConfiguration) -> list[LineTensionResult]:
    if not config.is_sufficient_for_analysis():
        return [LineTensionResult(line_id=f"LINE_{i+1:02d}")
                for i in range(config.number_of_lines or 0)]

    total_h = env_forces.total_horizontal_force_N or 0.0
    n_lines = config.number_of_lines

    results = []
    for i, segment in enumerate(_unique_lines(config)):
        if segment.length_m is None or segment.weight_per_m is None:
            results.append(LineTensionResult(line_id=segment.line_id))
            continue

        # Distribute horizontal force across lines (simplified: equal share for now)
        line_h_force = total_h / n_lines if n_lines else 0.0

        cat = catenary_tension(
            horizontal_force_N=line_h_force,
            water_depth_m=config.water_depth_m,
            line_length_m=segment.length_m,
            weight_per_m=segment.weight_per_m,
            pretension_N=(config.pretension_N or 0.0) / n_lines if n_lines else 0.0,
            seabed_friction=config.seabed_friction_coefficient or 0.0,
        )

        if "error" in cat:
            results.append(LineTensionResult(line_id=segment.line_id))
            continue

        utilization = None
        safety_factor = None
        if segment.breaking_strength_N and segment.breaking_strength_N > 0:
            utilization = round(cat["resultant_tension_N"] / segment.breaking_strength_N, 4)
            safety_factor = round(segment.breaking_strength_N / cat["resultant_tension_N"], 2) if cat["resultant_tension_N"] > 0 else None

        results.append(LineTensionResult(
            line_id=segment.line_id,
            estimated_tension_N=cat["resultant_tension_N"],
            horizontal_tension_N=cat["horizontal_tension_N"],
            vertical_tension_N=cat["vertical_tension_N"],
            line_angle_deg=cat["line_angle_deg"],
            utilization_ratio=utilization,
            safety_factor=safety_factor,
            model_status="VALIDATED_INPUTS",
        ))

    return results


def compute_mooring_estimate(buoy_id: str, observation_timestamp: str,
                             telemetry: dict, config: MooringConfiguration,
                             event_id: str) -> MooringEstimate:
    from datetime import datetime, timezone
    calculated_at = datetime.now(timezone.utc).isoformat()

    if not config.is_sufficient_for_analysis():
        env = compute_environmental_forces(telemetry, config)
        return MooringEstimate(
            event_id=event_id, buoy_id=buoy_id,
            source_observation_timestamp=observation_timestamp,
            calculated_at=calculated_at,
            environmental_forces=env,
            model_status="INSUFFICIENT_CONFIGURATION",
        )

    env = compute_environmental_forces(telemetry, config)
    lines = compute_line_tensions(env, config)

    tensions = [l.estimated_tension_N for l in lines if l.estimated_tension_N is not None]
    utilizations = [l.utilization_ratio for l in lines if l.utilization_ratio is not None]

    max_tension = max(tensions) if tensions else None
    max_util = max(utilizations) if utilizations else None

    if max_util is not None:
        if max_util > 0.8:
            risk_level = "HIGH"
        elif max_util > 0.5:
            risk_level = "MODERATE"
        else:
            risk_level = "LOW"
    else:
        risk_level = "UNKNOWN"

    return MooringEstimate(
        event_id=event_id, buoy_id=buoy_id,
        source_observation_timestamp=observation_timestamp,
        calculated_at=calculated_at,
        environmental_forces=env,
        lines=lines,
        max_tension_N=max_tension,
        max_utilization=max_util,
        risk_level=risk_level,
        model_status="VALIDATED_INPUTS" if all(l.model_status == "VALIDATED_INPUTS" for l in lines) else "PARTIAL_INPUTS",
    )


def _metric_value(group: dict, key: str) -> float | None:
    metric = group.get(key)
    if metric is None:
        return None
    v = metric.get("value") if isinstance(metric, dict) else None
    return v if isinstance(v, (int, float)) else None


def _unique_lines(config: MooringConfiguration) -> list:
    """Get one representative segment per unique line_id."""
    seen = set()
    result = []
    for seg in config.line_segments:
        if seg.line_id not in seen:
            seen.add(seg.line_id)
            result.append(seg)
    return result
