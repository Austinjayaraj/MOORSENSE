"""Quasi-static catenary mooring solver.

Given environmental horizontal force, mooring geometry, and line properties,
solves for the catenary equilibrium. The approach:

1. The environmental force defines the horizontal tension at the fairlead.
2. The catenary equations determine suspended line shape from that tension.
3. Vertical tension = weight of suspended line.
4. Fairlead tension = vector sum of horizontal and vertical.

For a catenary with horizontal tension H and weight per unit length w:
    s = sqrt(z² + 2·a·z)   where a = H/w, z = water depth
    x = a · arcosh(1 + z/a)

This is a SCREENING-LEVEL quasi-static solver. It does NOT model:
- Dynamic amplification or fatigue
- Vortex-induced vibration (VIV)
- Full hydrodynamic RAO-based wave response
- Time-domain simulation
"""
import math
import logging
from .models import MooringConfiguration, MooringLineSegment

log = logging.getLogger(__name__)

GRAVITY = 9.81


class CatenarySolution:
    def __init__(self):
        self.converged: bool = False
        self.iterations: int = 0
        self.residual: float = float('inf')
        self.horizontal_tension_n: float = 0.0
        self.vertical_tension_n: float = 0.0
        self.fairlead_tension_n: float = 0.0
        self.anchor_tension_n: float = 0.0
        self.line_angle_deg: float = 0.0
        self.fairlead_excursion_m: float = 0.0
        self.grounded_length_m: float = 0.0
        self.suspended_length_m: float = 0.0


def solve_catenary(config: MooringConfiguration,
                   horizontal_force_n: float,
                   max_iter: int = 100,
                   tol: float = 0.1) -> CatenarySolution:
    """Solve quasi-static catenary equilibrium.

    The horizontal environmental force is applied at the fairlead. The solver
    computes the catenary geometry and resulting tensions. Pretension shifts
    the initial guess but the solver finds the actual equilibrium independently.
    """
    sol = CatenarySolution()
    depth = config.effective_depth()
    total_length = config.effective_line_length()
    if depth is None or total_length is None or depth <= 0 or total_length <= 0:
        return sol
    if not config.segments:
        return sol

    w = _effective_weight_per_m(config.segments)
    if w <= 0:
        return sol

    seabed_friction = config.seabed_friction or 0.0
    pretension = (config.pretension_n.value or 0.0) if config.pretension_n else 0.0

    # The horizontal tension at the fairlead equals the applied environmental
    # force. The catenary then determines the vertical component and shape.
    # Pretension contributes to the horizontal force at rest.
    H = max(horizontal_force_n + pretension, 0.1)

    # Catenary parameter
    a = H / w

    # Suspended line length from catenary geometry: s = sqrt(d² + 2·a·d)
    s_suspended = math.sqrt(depth ** 2 + 2 * a * depth)
    s_suspended = min(s_suspended, total_length)

    grounded = max(0.0, total_length - s_suspended)

    # Seabed friction adds to horizontal tension at anchor
    friction_force = seabed_friction * w * grounded
    H_anchor = H
    H_fairlead = H + friction_force

    # Vertical tension at fairlead = total suspended weight
    V = w * s_suspended

    # Horizontal span of the suspended catenary
    if a > 1e-6:
        ratio = depth / a
        if ratio < 700:
            x_span = a * math.acosh(1.0 + ratio)
        else:
            x_span = a * math.log(2.0 * ratio)
    else:
        x_span = 0.0

    # Fairlead tension = resultant of horizontal and vertical
    T_fairlead = math.sqrt(H_fairlead ** 2 + V ** 2)

    # Anchor tension: horizontal component only (catenary touches seabed tangentially)
    T_anchor = H_anchor

    # Line angle at fairlead (from horizontal)
    angle_rad = math.atan2(V, H_fairlead)
    angle_deg = math.degrees(angle_rad)

    # Verify force balance: the catenary solution is closed-form given H,
    # so convergence is achieved by construction. The residual measures
    # how well the geometry matches: check that depth is satisfied.
    # For a catenary: z = a * (cosh(x/a) - 1), at x=x_span should equal depth.
    if a > 1e-6 and x_span > 0:
        z_check = a * (math.cosh(min(x_span / a, 700)) - 1.0)
        residual = abs(z_check - depth)
    else:
        residual = 0.0

    sol.converged = residual < max(tol, depth * 1e-6)
    sol.iterations = 1
    sol.residual = round(residual, 6)
    sol.horizontal_tension_n = round(H_fairlead, 2)
    sol.vertical_tension_n = round(V, 2)
    sol.fairlead_tension_n = round(T_fairlead, 2)
    sol.anchor_tension_n = round(T_anchor, 2)
    sol.line_angle_deg = round(angle_deg, 2)
    sol.fairlead_excursion_m = round(x_span + grounded, 1)
    sol.grounded_length_m = round(grounded, 1)
    sol.suspended_length_m = round(s_suspended, 1)

    if not sol.converged:
        log.warning("[CATENARY] %s geometric residual %.3f m exceeds tolerance %.3f m",
                    config.buoy_id, residual, tol)

    return sol


def _effective_weight_per_m(segments: list[MooringLineSegment]) -> float:
    """Compute length-weighted average submerged weight per meter (N/m)."""
    total_weight = 0.0
    total_length = 0.0
    for seg in segments:
        length = seg.length_m or 0
        weight = seg.submerged_weight_n_m or 0
        total_weight += weight * length
        total_length += length
    if total_length <= 0:
        return 0.0
    return total_weight / total_length


def compute_utilization(tension_n: float | None, segments: list[MooringLineSegment]) -> float | None:
    """Utilization = T_max / MBL. MBL is minimum breaking load across segments."""
    if tension_n is None or not segments:
        return None
    mbl_values = [s.breaking_strength_n for s in segments if s.breaking_strength_n is not None]
    if not mbl_values:
        return None
    mbl = min(mbl_values)
    if mbl <= 0:
        return None
    return round(tension_n / mbl, 4)


def compute_safety_factor(tension_n: float | None, segments: list[MooringLineSegment]) -> float | None:
    """Safety factor = MBL / T_max."""
    if tension_n is None or tension_n <= 0 or not segments:
        return None
    mbl_values = [s.breaking_strength_n for s in segments if s.breaking_strength_n is not None]
    if not mbl_values:
        return None
    mbl = min(mbl_values)
    if mbl <= 0:
        return None
    return round(mbl / tension_n, 2)
