"""Physics audit tests for Parts 1-4 of the MoorSense final integration phase.

Covers:
- True 2D equilibrium with Fx/Fy residual verification
- Force symmetry (reversing direction reverses offset)
- Coordinate convention (FROM→force direction)
- Vertical equilibrium (conceptual check)
- Mooring restoring force via catenary solver
- Wind/current/wave direction convention
- Physics diagnostics
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest

from services.mooring.models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
    EnvironmentalForceResult,
)
from services.mooring.buoy_equilibrium import (
    solve_equilibrium, EquilibriumSolution, _catenary_horizontal_tension_at_offset,
)
from services.mooring.environmental_forces import (
    wind_force, current_force_on_buoy, wave_force_morison,
    _from_bearing_to_force_rad, compute_environmental_forces,
)
from services.mooring.models import EnvironmentalState
from services.mooring.catenary_solver import solve_catenary

CONVERGENCE_TOL = 5.0  # N — test tolerance for force residuals


def _make_config(depth=3000, ll=3660, w=5.0, mbl=250000):
    return MooringConfiguration(
        buoy_id="TEST",
        water_depth=ProvenancedValue(value=depth, unit="m",
            provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
        total_line_length=ProvenancedValue(value=ll, unit="m",
            provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
        segments=[MooringLineSegment(name="m", length_m=ll,
                                     submerged_weight_n_m=w, breaking_strength_n=mbl)])


def _forces(mag, bearing_toward_deg):
    """Create force vector with magnitude toward a given bearing."""
    rad = math.radians(bearing_toward_deg)
    fx = mag * math.sin(rad)
    fy = mag * math.cos(rad)
    return EnvironmentalForceResult(
        total_horizontal_n=mag, total_direction_deg=bearing_toward_deg,
        total_fx=fx, total_fy=fy)


# ── Part 1: 2D Equilibrium with Fx/Fy Residual ──────────────────────────────

class TestTrueEquilibrium:
    """Verify Fx_residual and Fy_residual are both within tolerance at convergence."""

    def test_converged_residual_x_within_tolerance(self):
        sol = solve_equilibrium(_make_config(), _forces(5000.0, 90.0))
        assert sol.converged
        assert sol.fx_residual_n is not None
        assert abs(sol.fx_residual_n) < CONVERGENCE_TOL

    def test_converged_residual_y_within_tolerance(self):
        sol = solve_equilibrium(_make_config(), _forces(5000.0, 90.0))
        assert sol.converged
        assert sol.fy_residual_n is not None
        assert abs(sol.fy_residual_n) < CONVERGENCE_TOL

    def test_vector_residual_magnitude_exposed(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 45.0))
        assert sol.force_residual_magnitude_n is not None
        assert sol.force_residual_magnitude_n >= 0

    def test_converged_vector_residual_small(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 45.0))
        if sol.converged:
            assert sol.force_residual_magnitude_n < CONVERGENCE_TOL

    def test_residuals_exposed_even_when_not_converged(self):
        """Even a failed solve must expose residuals, not hide them."""
        sol = solve_equilibrium(_make_config(), _forces(5000.0, 0.0))
        # Whether converged or not, residuals must be present after a solve attempt
        if sol.solver_status not in ("INSUFFICIENT_CONFIGURATION", "NOT_RUN"):
            assert sol.fx_residual_n is not None or sol.equilibrium_residual_n is not None

    def test_offset_x_y_consistent_with_bearing(self):
        """For eastward force (90°), offset should be predominantly eastward (Ox > 0, Oy ≈ 0)."""
        sol = solve_equilibrium(_make_config(), _forces(5000.0, 90.0))
        if sol.converged and sol.predicted_offset_x_m is not None:
            assert sol.predicted_offset_x_m > 0
            assert abs(sol.predicted_offset_y_m) < 1.0  # minimal N component

    def test_northward_force_gives_northward_offset(self):
        """For northward force (0°), offset should be predominantly northward (Oy > 0)."""
        sol = solve_equilibrium(_make_config(), _forces(5000.0, 0.0))
        if sol.converged and sol.predicted_offset_y_m is not None:
            assert sol.predicted_offset_y_m > 0
            assert abs(sol.predicted_offset_x_m) < 1.0

    # Part 1A: All 10 required test scenarios

    def test_zero_environmental_force(self):
        sol = solve_equilibrium(_make_config(),
            EnvironmentalForceResult(total_horizontal_n=0.0, total_fx=0.0, total_fy=0.0))
        assert sol.solver_status == "CONVERGED"
        assert sol.predicted_offset_m == pytest.approx(0.0, abs=0.01)

    def test_positive_x_force(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 90.0))  # +East
        assert sol.converged
        assert sol.predicted_offset_m > 0

    def test_negative_x_force(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 270.0))  # -East (West)
        assert sol.converged
        assert sol.predicted_offset_m > 0  # magnitude is always positive

    def test_positive_y_force(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 0.0))  # +North
        assert sol.converged
        assert sol.predicted_offset_m > 0

    def test_negative_y_force(self):
        sol = solve_equilibrium(_make_config(), _forces(3000.0, 180.0))  # -North (South)
        assert sol.converged
        assert sol.predicted_offset_m > 0

    def test_diagonal_force(self):
        sol = solve_equilibrium(_make_config(), _forces(4000.0, 45.0))
        assert sol.converged
        assert sol.predicted_offset_m > 0

    def test_impossible_geometry_no_segments(self):
        config = MooringConfiguration(buoy_id="T")
        sol = solve_equilibrium(config, _forces(5000.0, 90.0))
        assert sol.solver_status == "INSUFFICIENT_CONFIGURATION"

    def test_maximum_iteration_limit(self):
        """Solver must terminate and report status even under extreme force.
        Either FAILED (no upper bound found) or WARNING/CONVERGED after iterations."""
        sol = solve_equilibrium(_make_config(), _forces(1e9, 90.0))  # extreme force
        assert sol.solver_status in ("CONVERGED", "WARNING", "FAILED")
        # iterations is 0 for early FAILED (no upper bound), or > 0 for bisection
        assert isinstance(sol.iterations, int)
        assert sol.iterations >= 0


# Part 1B: Symmetry tests

class TestEquilibriumSymmetry:
    def test_east_west_force_symmetry(self):
        """Reversing force direction reverses offset components (same magnitude)."""
        sol_e = solve_equilibrium(_make_config(), _forces(3000.0, 90.0))
        sol_w = solve_equilibrium(_make_config(), _forces(3000.0, 270.0))
        if sol_e.converged and sol_w.converged:
            assert abs(sol_e.predicted_offset_m - sol_w.predicted_offset_m) < 0.5
            if sol_e.predicted_offset_x_m and sol_w.predicted_offset_x_m:
                assert sol_e.predicted_offset_x_m == pytest.approx(-sol_w.predicted_offset_x_m, abs=1.0)

    def test_north_south_force_symmetry(self):
        sol_n = solve_equilibrium(_make_config(), _forces(3000.0, 0.0))
        sol_s = solve_equilibrium(_make_config(), _forces(3000.0, 180.0))
        if sol_n.converged and sol_s.converged:
            assert abs(sol_n.predicted_offset_m - sol_s.predicted_offset_m) < 0.5
            if sol_n.predicted_offset_y_m and sol_s.predicted_offset_y_m:
                assert sol_n.predicted_offset_y_m == pytest.approx(-sol_s.predicted_offset_y_m, abs=1.0)

    def test_offset_magnitude_independent_of_direction(self):
        """For symmetric mooring, same force magnitude → same offset magnitude."""
        F = 5000.0
        offsets = []
        for bearing in [0.0, 45.0, 90.0, 135.0, 180.0, 225.0, 270.0, 315.0]:
            sol = solve_equilibrium(_make_config(), _forces(F, bearing))
            if sol.converged and sol.predicted_offset_m:
                offsets.append(sol.predicted_offset_m)
        if len(offsets) >= 4:
            # All offsets should be nearly identical (radial symmetry)
            mean = sum(offsets) / len(offsets)
            for o in offsets:
                assert abs(o - mean) / mean < 0.01  # within 1%


# ── Part 2: Coordinate Convention ────────────────────────────────────────────

class TestCoordinateConvention:
    """FROM-bearing to force-direction conversion: (FROM + 180) % 360."""

    def test_north_wind_acts_southward(self):
        """Wind FROM 0° (North) → force toward South → Fy < 0, Fx ≈ 0."""
        _, fx, fy = wind_force(10.0, 5.0, 0.0)  # FROM North
        assert fx == pytest.approx(0.0, abs=0.01)
        assert fy < 0  # southward

    def test_east_wind_acts_westward(self):
        """Wind FROM 90° (East) → force toward West → Fx < 0, Fy ≈ 0."""
        _, fx, fy = wind_force(10.0, 5.0, 90.0)  # FROM East
        assert fy == pytest.approx(0.0, abs=0.01)
        assert fx < 0  # westward

    def test_south_wind_acts_northward(self):
        """Wind FROM 180° (South) → force toward North → Fy > 0, Fx ≈ 0."""
        _, fx, fy = wind_force(10.0, 5.0, 180.0)  # FROM South
        assert fx == pytest.approx(0.0, abs=0.01)
        assert fy > 0  # northward

    def test_west_wind_acts_eastward(self):
        """Wind FROM 270° (West) → force toward East → Fx > 0, Fy ≈ 0."""
        _, fx, fy = wind_force(10.0, 5.0, 270.0)
        assert fy == pytest.approx(0.0, abs=0.01)
        assert fx > 0  # eastward

    def test_from_bearing_conversion_helper(self):
        assert _from_bearing_to_force_rad(0.0) == pytest.approx(math.pi, rel=1e-6)
        assert _from_bearing_to_force_rad(90.0) == pytest.approx(math.radians(270), rel=1e-6)
        assert _from_bearing_to_force_rad(180.0) == pytest.approx(0.0, abs=1e-10)
        assert _from_bearing_to_force_rad(270.0) == pytest.approx(math.radians(90), rel=1e-6)

    def test_current_direction_same_convention_as_wind(self):
        """Current FROM 0° (North) should also push buoy south (Fy < 0)."""
        _, fx, fy = current_force_on_buoy(1.0, 3.0, 0.0)
        assert fy < 0
        assert abs(fx) < 0.01

    def test_force_magnitude_unchanged_by_direction(self):
        """Magnitude must not depend on direction (only speed/area)."""
        m0, _, _ = wind_force(10.0, 5.0, 0.0)
        m90, _, _ = wind_force(10.0, 5.0, 90.0)
        m180, _, _ = wind_force(10.0, 5.0, 180.0)
        assert m0 == pytest.approx(m90, rel=1e-6)
        assert m0 == pytest.approx(m180, rel=1e-6)

    def test_force_vector_components_sum_to_magnitude(self):
        """||(Fx, Fy)|| must equal the scalar magnitude."""
        for bearing in [0.0, 45.0, 90.0, 135.0, 180.0]:
            mag, fx, fy = wind_force(10.0, 5.0, bearing)
            vec_mag = math.sqrt(fx ** 2 + fy ** 2)
            assert vec_mag == pytest.approx(mag, rel=1e-6)


# ── Part 3: Vertical Equilibrium (Conceptual) ─────────────────────────────────

class TestVerticalEquilibriumConcept:
    """Vertical equilibrium: buoyancy - weight - vertical_mooring_reaction ≈ 0.

    The catenary vertical tension at the fairlead equals the suspended line weight.
    For static equilibrium: buoyancy must support buoy weight + vertical line tension.
    This is a conceptual check — buoy geometry is REFERENCE/ASSUMPTION.
    """

    def test_catenary_vertical_tension_is_suspended_line_weight(self):
        """Vertical tension = w * suspended_length (within solver precision)."""
        config = _make_config(depth=3000, ll=3660, w=5.0)
        sol = solve_catenary(config, horizontal_force_n=5000.0)
        if sol.converged:
            expected_v = 5.0 * sol.suspended_length_m
            assert sol.vertical_tension_n == pytest.approx(expected_v, rel=0.01)

    def test_fairlead_tension_is_vector_sum(self):
        """T_fairlead^2 = H^2 + V^2."""
        config = _make_config()
        sol = solve_catenary(config, horizontal_force_n=5000.0)
        if sol.converged:
            expected_T = math.sqrt(sol.horizontal_tension_n ** 2 + sol.vertical_tension_n ** 2)
            assert sol.fairlead_tension_n == pytest.approx(expected_T, rel=0.01)


# ── Part 4: Mooring Restoring Force Uses Catenary ────────────────────────────

class TestMooringRestoring:
    def test_catenary_called_for_restoring_force(self):
        """_catenary_horizontal_tension_at_offset must use the catenary solver."""
        config = _make_config()
        H, sol = _catenary_horizontal_tension_at_offset(config, 50.0)
        assert H > 0
        # The catenary solution must be consistent with the horizontal tension
        # catenary_param a = H/w, and horizontal span should match target
        from services.mooring.catenary_solver import _effective_weight_per_m
        w = _effective_weight_per_m(config.segments)
        a = H / w
        depth = config.effective_depth()
        if a > 1e-9 and depth:
            ratio = depth / a
            if ratio < 700:
                x_span = a * math.acosh(1.0 + ratio)
            else:
                x_span = a * math.log(2.0 * ratio)
            assert abs(x_span - 50.0) < 1.0  # within 1m

    def test_restoring_increases_with_offset(self):
        """Mooring stiffens with displacement — H must increase with offset."""
        config = _make_config()
        H1, _ = _catenary_horizontal_tension_at_offset(config, 10.0)
        H2, _ = _catenary_horizontal_tension_at_offset(config, 50.0)
        H3, _ = _catenary_horizontal_tension_at_offset(config, 200.0)
        assert H2 > H1
        assert H3 > H2

    def test_restoring_zero_for_zero_offset(self):
        """Zero offset → zero restoring force (no strain)."""
        config = _make_config()
        H, _ = _catenary_horizontal_tension_at_offset(config, 0.0)
        assert H == 0.0
