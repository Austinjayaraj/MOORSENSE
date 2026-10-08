"""Environmental force engine with proper vector decomposition.

COORDINATE SYSTEM:
    +X = East,  +Y = North
    Bearing convention: 0° = North, 90° = East (navigation standard).

DIRECTION CONVENTION (INCOIS / meteorological):
    Wind/current direction is FROM which direction the agent comes.
    A wind "from 0°" (North) pushes the buoy SOUTH.
    Conversion: force_bearing = (from_bearing + 180) % 360
    Fx = F_mag * sin(radians(force_bearing))
    Fy = F_mag * cos(radians(force_bearing))

Forces are computed as (Fx, Fy) vectors, never scalar-added.
"""
import math
from .models import EnvironmentalState, EnvironmentalForceResult, MooringConfiguration

RHO_AIR = 1.225       # kg/m³
RHO_WATER = 1025.0    # kg/m³
GRAVITY = 9.81         # m/s²
CD_WIND = 1.2
CD_CURRENT_LINE = 1.2
CD_CURRENT_BUOY = 1.0


def _from_bearing_to_force_rad(from_bearing_deg: float) -> float:
    """Convert FROM-bearing to force-direction radians.

    Meteorological FROM direction: wind/current arrives FROM this bearing.
    The resulting force acts TOWARD (from_bearing + 180) % 360.
    Returns the force direction in radians.
    """
    return math.radians((from_bearing_deg + 180.0) % 360.0)


def wind_force(speed_ms: float, projected_area_m2: float,
               from_direction_deg: float, cd: float = CD_WIND) -> tuple[float, float, float]:
    """Wind drag force vector. Returns (magnitude, fx, fy).

    from_direction_deg: meteorological bearing FROM which wind arrives.
    A north wind (from_direction=0°) pushes the buoy south (Fy < 0).
    Force direction = (from_direction + 180) % 360.
    """
    f_mag = 0.5 * RHO_AIR * cd * projected_area_m2 * speed_ms ** 2
    force_rad = _from_bearing_to_force_rad(from_direction_deg)
    return f_mag, f_mag * math.sin(force_rad), f_mag * math.cos(force_rad)


def current_force_on_buoy(speed_ms: float, submerged_area_m2: float,
                          from_direction_deg: float, cd: float = CD_CURRENT_BUOY) -> tuple[float, float, float]:
    """Current drag on the buoy hull.

    from_direction_deg: meteorological bearing FROM which current arrives.
    """
    f_mag = 0.5 * RHO_WATER * cd * submerged_area_m2 * speed_ms ** 2
    force_rad = _from_bearing_to_force_rad(from_direction_deg)
    return f_mag, f_mag * math.sin(force_rad), f_mag * math.cos(force_rad)


def current_force_on_line(segments: list, water_depth_m: float,
                          current_speed_ms: float, current_direction_deg: float,
                          current_profile: list[dict] | None = None) -> tuple[float, float, float]:
    """Current drag integrated along mooring line segments.

    Uses current profile when available; otherwise assumes uniform surface current
    decaying linearly to zero at the seabed.
    """
    if not segments or current_speed_ms is None:
        return 0.0, 0.0, 0.0

    n_elements = 50
    total_fx, total_fy = 0.0, 0.0
    dz = water_depth_m / n_elements if water_depth_m > 0 else 1.0
    dir_rad = _from_bearing_to_force_rad(current_direction_deg)

    for i in range(n_elements):
        z = (i + 0.5) * dz
        v = _interpolate_current(z, water_depth_m, current_speed_ms, current_profile)
        seg = _segment_at_depth(segments, z, water_depth_m)
        if seg is None:
            continue
        diameter = seg.diameter_m or 0.032
        cd = seg.drag_coefficient
        df = 0.5 * RHO_WATER * cd * diameter * v ** 2 * dz
        total_fx += df * math.sin(dir_rad)
        total_fy += df * math.cos(dir_rad)

    mag = math.sqrt(total_fx ** 2 + total_fy ** 2)
    return mag, total_fx, total_fy


def _interpolate_current(z: float, depth: float, surface_speed: float,
                         profile: list[dict] | None) -> float:
    """Interpolate current speed at depth z (meters from surface)."""
    if profile and len(profile) >= 2:
        sorted_p = sorted(profile, key=lambda p: p.get("depth", 0))
        for i in range(len(sorted_p) - 1):
            d0, d1 = sorted_p[i].get("depth", 0), sorted_p[i + 1].get("depth", 0)
            if d0 <= z <= d1:
                frac = (z - d0) / (d1 - d0) if d1 > d0 else 0
                v0 = sorted_p[i].get("speed", 0) or 0
                v1 = sorted_p[i + 1].get("speed", 0) or 0
                return v0 + frac * (v1 - v0)
        if z <= sorted_p[0].get("depth", 0):
            return sorted_p[0].get("speed", 0) or 0
        return sorted_p[-1].get("speed", 0) or 0
    if depth <= 0:
        return surface_speed
    return surface_speed * max(0, 1 - z / depth)


def _segment_at_depth(segments: list, z: float, total_depth: float):
    """Find which mooring segment occupies depth z (simple proportional mapping)."""
    if not segments:
        return None
    total_len = sum(s.length_m or 0 for s in segments)
    if total_len <= 0:
        return segments[0]
    cumulative = 0.0
    frac = z / total_depth if total_depth > 0 else 0
    target_along_line = frac * total_len
    for seg in segments:
        cumulative += seg.length_m or 0
        if target_along_line <= cumulative:
            return seg
    return segments[-1]


def wave_force_morison(wave_height_m: float, wave_period_s: float,
                       wave_direction_deg: float, water_depth_m: float,
                       buoy_diameter_m: float, draft_m: float) -> tuple[float, float, float]:
    """Screening-level Morison wave force on the buoy.

    Uses linear wave theory for orbital velocity. This is explicitly a
    screening estimate, NOT a full hydrodynamic RAO analysis.
    """
    if wave_period_s <= 0 or water_depth_m <= 0:
        return 0.0, 0.0, 0.0

    omega = 2 * math.pi / wave_period_s
    k = _wave_number(omega, water_depth_m)

    u_max = omega * (wave_height_m / 2) * math.cosh(k * (water_depth_m - draft_m / 2)) / math.sinh(k * water_depth_m) if k * water_depth_m > 0.01 else omega * wave_height_m / 2
    a_max = omega * u_max

    cd_wave = 1.0
    cm_wave = 2.0
    area = buoy_diameter_m * draft_m
    volume = math.pi * (buoy_diameter_m / 2) ** 2 * draft_m

    f_drag = 0.5 * RHO_WATER * cd_wave * area * u_max * abs(u_max)
    f_inertia = RHO_WATER * cm_wave * volume * a_max

    f_mag = abs(f_drag) + abs(f_inertia)
    dir_rad = _from_bearing_to_force_rad(wave_direction_deg)
    return f_mag, f_mag * math.sin(dir_rad), f_mag * math.cos(dir_rad)


def _wave_number(omega: float, depth: float, tol: float = 1e-6, max_iter: int = 50) -> float:
    """Solve the dispersion relation omega² = gk·tanh(kd) iteratively."""
    k = omega ** 2 / GRAVITY
    for _ in range(max_iter):
        kd = k * depth
        tanh_kd = math.tanh(min(kd, 20))
        f = omega ** 2 - GRAVITY * k * tanh_kd
        fp = -GRAVITY * (tanh_kd + k * depth * (1 - tanh_kd ** 2))
        if abs(fp) < 1e-15:
            break
        k_new = k - f / fp
        if abs(k_new - k) < tol:
            return max(k_new, 1e-10)
        k = max(k_new, 1e-10)
    return k


def compute_environmental_forces(env: EnvironmentalState,
                                 config: MooringConfiguration) -> EnvironmentalForceResult:
    """Compute all environmental forces and combine as vectors."""
    total_fx, total_fy = 0.0, 0.0
    result = EnvironmentalForceResult()

    depth = config.effective_depth() or 0
    buoy_diam = config.buoy_diameter_m.value if config.buoy_diameter_m else 2.7
    buoy_height = config.buoy_height_m.value if config.buoy_height_m else 3.2
    draft = buoy_height * 0.5
    proj_area = config.projected_area_m2.value if config.projected_area_m2 else math.pi * (buoy_diam / 2) ** 2
    submerged_area = buoy_diam * draft

    # Wind force
    if env.wind_speed_ms is not None and env.wind_direction_deg is not None:
        wf, wfx, wfy = wind_force(env.wind_speed_ms, proj_area, env.wind_direction_deg)
        result.wind_force_n = round(wf, 2)
        result.wind_fx = round(wfx, 2)
        result.wind_fy = round(wfy, 2)
        total_fx += wfx
        total_fy += wfy

    # Current force on buoy hull
    if env.current_speed_ms is not None and env.current_direction_deg is not None:
        cf, cfx, cfy = current_force_on_buoy(env.current_speed_ms, submerged_area, env.current_direction_deg)
        # Also add line drag if we have segments and depth
        if config.segments and depth > 0:
            lf, lfx, lfy = current_force_on_line(
                config.segments, depth, env.current_speed_ms, env.current_direction_deg,
                env.current_profile)
            cf += lf
            cfx += lfx
            cfy += lfy
        result.current_force_n = round(cf, 2)
        result.current_fx = round(cfx, 2)
        result.current_fy = round(cfy, 2)
        total_fx += cfx
        total_fy += cfy

    # Wave force
    if (env.wave_height_m is not None and env.wave_period_s is not None
            and env.wave_direction_deg is not None and depth > 0):
        wvf, wvfx, wvfy = wave_force_morison(
            env.wave_height_m, env.wave_period_s, env.wave_direction_deg,
            depth, buoy_diam, draft)
        result.wave_force_n = round(wvf, 2)
        result.wave_fx = round(wvfx, 2)
        result.wave_fy = round(wvfy, 2)
        total_fx += wvfx
        total_fy += wvfy

    total_h = math.sqrt(total_fx ** 2 + total_fy ** 2)
    result.total_horizontal_n = round(total_h, 2) if total_h > 0 else None
    result.total_fx = round(total_fx, 2)
    result.total_fy = round(total_fy, 2)
    if total_h > 0:
        result.total_direction_deg = round(math.degrees(math.atan2(total_fx, total_fy)) % 360, 1)
    return result
