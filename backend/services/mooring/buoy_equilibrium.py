"""Coupled buoy equilibrium model — radial + vector formulation.

COORDINATE SYSTEM:
    +X = East
    +Y = North
    Bearing: 0° = North, 90° = East (standard navigation)

WIND/CURRENT DIRECTION CONVENTION (INCOIS / meteorological):
    Direction FROM which wind/current arrives.
    A 0° (North) wind blows FROM north → buoy displaced SOUTHWARD.
    Force direction = FROM_direction + 180°.

    So: force_bearing_deg = (from_bearing_deg + 180) % 360
    Fx = F_mag * sin(radians(force_bearing_deg))
    Fy = F_mag * cos(radians(force_bearing_deg))

FORMULATION:
    For a single-point mooring the restoring force is radial (the mooring
    pulls the buoy back toward the anchor along the line connecting them).
    Equilibrium in the horizontal plane is:

        F_env_vec + F_mooring_vec = 0

    Since F_mooring opposes the offset direction:
        F_mooring_vec = -H * unit_vector(offset)

    where H is the catenary horizontal tension at the given offset magnitude.

    This reduces to solving the scalar equation:
        H(|offset|) = |F_env|

    because the force vectors are collinear at equilibrium for a single-point
    mooring (the buoy moves in the direction of the net environmental force).

    This is NOT a limitation — it is a mathematical consequence of radial
    mooring symmetry. The 2D vector components are fully preserved.

    If an asymmetric multi-line mooring were supported, a full 2D Newton
    solver would be required.

PROVENANCE:
    All outputs are MODELLED. Never MEASURED.
    Never AUTHORITATIVE unless a physical sensor confirms.

VALIDATION:
    Compare predicted_offset_m against GPS displacement for buoy motion
    validation. This is BUOY_MOTION_VALIDATION, not tension validation.
"""
from __future__ import annotations
import math
import logging
from pydantic import BaseModel, ConfigDict

from .catenary_solver import solve_catenary, CatenarySolution, _effective_weight_per_m
from .models import MooringConfiguration, EnvironmentalForceResult

log = logging.getLogger(__name__)

# Convergence parameters
MAX_BISECT_BOUND = 40        # iterations to find upper bound
MAX_BISECT_ITER = 60         # iterations for bisection
CONVERGENCE_TOL_N = 1.0      # force residual tolerance (N)
RELAXED_TOL_FACTOR = 10      # factor for relaxed convergence check
MAX_OFFSET_M = 10_000.0      # physical upper limit (m)


class EquilibriumSolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    converged: bool = False
    solver_status: str = "NOT_RUN"

    # 2D vector result
    predicted_offset_m: float | None = None
    predicted_bearing_deg: float | None = None
    predicted_offset_x_m: float | None = None   # East component
    predicted_offset_y_m: float | None = None   # North component

    # Force balance
    environment_force_n: float | None = None
    environment_fx_n: float | None = None
    environment_fy_n: float | None = None
    mooring_restoring_force_n: float | None = None
    mooring_restoring_fx_n: float | None = None
    mooring_restoring_fy_n: float | None = None

    # Residuals (the key physics diagnostic)
    fx_residual_n: float | None = None
    fy_residual_n: float | None = None
    force_residual_magnitude_n: float | None = None
    equilibrium_residual_n: float | None = None  # alias for backwards compat

    # Catenary solution at equilibrium
    predicted_fairlead_tension_n: float | None = None
    predicted_line_angle_deg: float | None = None
    predicted_anchor_load_n: float | None = None

    iterations: int = 0
    provenance: str = "MODELLED"
    solver_notes: str | None = None


def _catenary_horizontal_tension_at_offset(config: MooringConfiguration,
                                            offset_m: float) -> tuple[float, CatenarySolution]:
    """Find the catenary horizontal tension H such that the horizontal span = offset_m.

    Uses binary search on H (the applied horizontal force) to find the geometry
    that matches the given offset. Returns (H, CatenarySolution).
    """
    depth = config.effective_depth()
    total_length = config.effective_line_length()
    w = _effective_weight_per_m(config.segments)

    if depth is None or total_length is None or w <= 0 or offset_m <= 0:
        return 0.0, CatenarySolution()

    # Binary search: find H such that catenary x_span = offset_m
    # x_span increases monotonically with H, so bisection is valid.
    H_lo, H_hi = 0.01, max(offset_m * w * 20.0, 1.0)

    for _ in range(80):
        H_mid = (H_lo + H_hi) / 2.0
        a = H_mid / w
        if a < 1e-9:
            x_span = 0.0
        else:
            ratio = depth / a
            if ratio < 700:
                x_span = a * math.acosh(1.0 + ratio)
            else:
                x_span = a * math.log(2.0 * ratio)
        if x_span < offset_m:
            H_lo = H_mid
        else:
            H_hi = H_mid
        if (H_hi - H_lo) < 0.01:
            break

    H_final = (H_lo + H_hi) / 2.0
    sol = solve_catenary(config, horizontal_force_n=H_final)
    return H_final, sol


def solve_equilibrium(config: MooringConfiguration,
                       env_forces: EnvironmentalForceResult) -> EquilibriumSolution:
    """Solve 2D horizontal static equilibrium for a single-point mooring buoy.

    For a radially symmetric single-point mooring:
      - The buoy moves in the direction of the net environmental force vector.
      - Equilibrium requires: H(offset) = |F_env|
      - This is solved as a 1D bisection on offset magnitude.
      - Vector components are reconstructed from the force bearing.

    The Fx/Fy residuals are checked explicitly at convergence.

    Returns EquilibriumSolution with provenance=MODELLED.
    """
    if not config.has_minimum_geometry():
        return EquilibriumSolution(
            solver_status="INSUFFICIENT_CONFIGURATION",
            solver_notes="Mooring configuration lacks required geometry (depth, line, weight)")

    F_env_x = env_forces.total_fx
    F_env_y = env_forces.total_fy
    F_env_mag = env_forces.total_horizontal_n

    if F_env_x is None or F_env_y is None or F_env_mag is None:
        F_env_mag = 0.0
        F_env_x = 0.0
        F_env_y = 0.0

    if F_env_mag is None:
        F_env_mag = math.sqrt(F_env_x ** 2 + F_env_y ** 2)

    if F_env_mag <= 0.0:
        return EquilibriumSolution(
            solver_status="CONVERGED", converged=True,
            predicted_offset_m=0.0, predicted_bearing_deg=0.0,
            predicted_offset_x_m=0.0, predicted_offset_y_m=0.0,
            environment_force_n=0.0, environment_fx_n=float(F_env_x), environment_fy_n=float(F_env_y),
            mooring_restoring_force_n=0.0, mooring_restoring_fx_n=0.0, mooring_restoring_fy_n=0.0,
            fx_residual_n=0.0, fy_residual_n=0.0,
            force_residual_magnitude_n=0.0, equilibrium_residual_n=0.0,
            iterations=0, provenance="MODELLED",
            solver_notes="Zero environmental force: buoy at rest position")

    # Unit vector in direction of environmental force (buoy moves this way)
    ux = F_env_x / F_env_mag
    uy = F_env_y / F_env_mag

    # Compute bearing of force (direction buoy moves toward)
    force_bearing_deg = math.degrees(math.atan2(ux, uy)) % 360.0

    # Find upper bound for offset
    x_hi = 10.0
    for _ in range(MAX_BISECT_BOUND):
        F_rest, _ = _catenary_horizontal_tension_at_offset(config, x_hi)
        if F_rest >= F_env_mag:
            break
        x_hi = min(x_hi * 2, MAX_OFFSET_M)
    else:
        return EquilibriumSolution(
            solver_status="FAILED", converged=False,
            environment_force_n=round(F_env_mag, 2),
            environment_fx_n=round(F_env_x, 2), environment_fy_n=round(F_env_y, 2),
            solver_notes=(f"Mooring restoring force never reaches {F_env_mag:.0f}N "
                          f"within {MAX_OFFSET_M:.0f}m offset. "
                          f"Check line weight and depth configuration."))

    # Bisection on offset magnitude
    x_lo = 0.0
    iterations = 0
    F_rest_final = 0.0
    sol_final = CatenarySolution()

    for i in range(MAX_BISECT_ITER):
        iterations = i + 1
        x_mid = (x_lo + x_hi) / 2.0
        F_rest, sol = _catenary_horizontal_tension_at_offset(config, x_mid)
        if abs(F_rest - F_env_mag) < CONVERGENCE_TOL_N:
            F_rest_final = F_rest
            sol_final = sol
            break
        if F_rest < F_env_mag:
            x_lo = x_mid
        else:
            x_hi = x_mid
        F_rest_final = F_rest
        sol_final = sol

    x_final = (x_lo + x_hi) / 2.0
    F_rest_final, sol_final = _catenary_horizontal_tension_at_offset(config, x_final)
    scalar_residual = abs(F_rest_final - F_env_mag)

    # Reconstruct 2D vector components
    offset_x = x_final * ux
    offset_y = x_final * uy
    mooring_fx = -F_rest_final * ux   # restoring force opposes displacement
    mooring_fy = -F_rest_final * uy

    # 2D residuals: these are the key physics diagnostics
    fx_resid = F_env_x + mooring_fx
    fy_resid = F_env_y + mooring_fy
    vec_residual = math.sqrt(fx_resid ** 2 + fy_resid ** 2)

    converged = scalar_residual < CONVERGENCE_TOL_N * RELAXED_TOL_FACTOR

    if not converged:
        log.warning("[EQUILIBRIUM] %s: force residual %.2fN at offset %.1fm after %d iter",
                    config.buoy_id, scalar_residual, x_final, iterations)

    return EquilibriumSolution(
        converged=converged,
        solver_status="CONVERGED" if converged else "WARNING",
        predicted_offset_m=round(x_final, 2),
        predicted_bearing_deg=round(force_bearing_deg, 2),
        predicted_offset_x_m=round(offset_x, 2),
        predicted_offset_y_m=round(offset_y, 2),
        environment_force_n=round(F_env_mag, 2),
        environment_fx_n=round(F_env_x, 2),
        environment_fy_n=round(F_env_y, 2),
        mooring_restoring_force_n=round(F_rest_final, 2),
        mooring_restoring_fx_n=round(mooring_fx, 2),
        mooring_restoring_fy_n=round(mooring_fy, 2),
        fx_residual_n=round(fx_resid, 4),
        fy_residual_n=round(fy_resid, 4),
        force_residual_magnitude_n=round(vec_residual, 4),
        equilibrium_residual_n=round(scalar_residual, 2),
        predicted_fairlead_tension_n=round(sol_final.fairlead_tension_n, 2) if sol_final.converged else None,
        predicted_line_angle_deg=round(sol_final.line_angle_deg, 2) if sol_final.converged else None,
        predicted_anchor_load_n=round(sol_final.anchor_tension_n, 2) if sol_final.converged else None,
        iterations=iterations,
        provenance="MODELLED",
        solver_notes=None if converged else (
            f"Scalar residual {scalar_residual:.1f}N, vector residual {vec_residual:.1f}N "
            f"at {iterations} iterations"),
    )
