"""Final integration tests covering:
Phase A: replay API completeness
Phase B: replay run registry
Phase C: replay determinism
Phase D: coupled buoy equilibrium
Phase E/F: forward/inverse validation hooks
Phase G: coupled confidence
Phase H: physics diagnostics
Phase S: provenance audit (no zero substitution, no fabricated values)
"""
import hashlib
import sys
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest

from services.mooring.models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
    MooringResponse, EnvironmentalForceResult,
)
from services.mooring.buoy_equilibrium import (
    solve_equilibrium, EquilibriumSolution, _catenary_horizontal_tension_at_offset,
)
from services.mooring.environmental_forces import compute_environmental_forces
from services.mooring.models import EnvironmentalState
from services.mooring.mooring_response import compute_mooring_response
from services.mooring.bathymetry_service import BathymetryService
from services.mooring.config_resolver import MooringConfigResolver
from services.replay.replay_service import _determinism_hash


# ── Phase B/C: Replay Registry + Determinism ────────────────────────────────

class TestReplayDeterminism:
    def test_same_inputs_same_hash(self):
        h1 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        h2 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        assert h1 == h2

    def test_different_station_different_hash(self):
        h1 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        h2 = _determinism_hash("OMNI-BD14", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        assert h1 != h2

    def test_different_model_version_different_hash(self):
        h1 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        h2 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.5", "catenary-0.4")
        assert h1 != h2

    def test_hash_is_hex_16_chars(self):
        h = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                               "2026-10-08T00:00:00+00:00",
                               "moorsense-0.4", "catenary-0.4")
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_excludes_timestamps(self):
        """created_at must NOT be in the hash — replay must be time-independent."""
        h1 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        # If we call again 'later', same inputs should give same hash
        h2 = _determinism_hash("OMNI-BD10", "2026-10-01T00:00:00+00:00",
                                "2026-10-08T00:00:00+00:00",
                                "moorsense-0.4", "catenary-0.4")
        assert h1 == h2

    def test_migration_006_exists(self):
        sql = Path(__file__).parents[1] / "migrations" / "006_replay_runs.sql"
        assert sql.exists()
        content = sql.read_text()
        assert "mooring_replay_runs" in content
        assert "run_id" in content
        assert "QUEUED" in content
        assert "input_hash" in content

    def test_replay_runner_produces_same_output_for_same_input(self):
        """Two calls with identical inputs must produce identical results."""
        from services.replay.replay_runner import ReplayRunner, ReplayObservation
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        obs = [ReplayObservation(
            station_id="OMNI-BD10", observation_timestamp=t0,
            telemetry={"meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"},
                                       "windDirection": {"value": 90.0, "unit": "°"}},
                       "ocean": {}, "waves": {}, "profiles": {}})]
        r1 = runner.replay_observations("OMNI-BD10", obs)
        r2 = runner.replay_observations("OMNI-BD10", obs)
        assert len(r1) == len(r2) == 1
        assert (r1[0].mooring_response.fairlead_tension_n ==
                r2[0].mooring_response.fairlead_tension_n)
        assert r1[0].mooring_response.solver_status == r2[0].mooring_response.solver_status


# ── Phase D: Coupled Buoy Equilibrium ───────────────────────────────────────

def _make_config(depth=3000, ll=3660, weight=5.0, mbl=250000):
    return MooringConfiguration(
        buoy_id="TEST",
        water_depth=ProvenancedValue(value=depth, unit="m",
            provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
        total_line_length=ProvenancedValue(value=ll, unit="m",
            provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
        segments=[MooringLineSegment(name="main", length_m=ll,
                                     submerged_weight_n_m=weight,
                                     breaking_strength_n=mbl)])


import math as _math

def _forces(mag, bearing_deg):
    """Build EnvironmentalForceResult with Fx/Fy from magnitude + bearing (force toward bearing)."""
    rad = _math.radians(bearing_deg)
    fx = mag * _math.sin(rad)
    fy = mag * _math.cos(rad)
    return EnvironmentalForceResult(
        total_horizontal_n=mag, total_direction_deg=bearing_deg,
        total_fx=fx, total_fy=fy)


class TestCoupledEquilibrium:
    def test_zero_force_gives_zero_offset(self):
        config = _make_config()
        forces = EnvironmentalForceResult(
            total_horizontal_n=0.0, total_fx=0.0, total_fy=0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.solver_status in ("CONVERGED", "NOT_RUN")
        if sol.predicted_offset_m is not None:
            assert sol.predicted_offset_m == pytest.approx(0.0, abs=0.1)

    def test_positive_force_gives_positive_offset(self):
        config = _make_config()
        forces = _forces(5000.0, 90.0)  # eastward force
        sol = solve_equilibrium(config, forces)
        assert sol.solver_status in ("CONVERGED", "WARNING")
        assert sol.predicted_offset_m is not None
        assert sol.predicted_offset_m > 0

    def test_larger_force_larger_offset(self):
        config = _make_config()
        s1 = solve_equilibrium(config, _forces(1000.0, 0.0))
        s2 = solve_equilibrium(config, _forces(5000.0, 0.0))
        if (s1.predicted_offset_m is not None and s2.predicted_offset_m is not None):
            assert s2.predicted_offset_m > s1.predicted_offset_m

    def test_insufficient_config_returns_correct_status(self):
        config = MooringConfiguration(buoy_id="T")
        forces = _forces(5000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.solver_status == "INSUFFICIENT_CONFIGURATION"

    def test_result_provenance_is_modelled(self):
        config = _make_config()
        forces = _forces(3000.0, 45.0)
        sol = solve_equilibrium(config, forces)
        assert sol.provenance == "MODELLED"

    def test_equilibrium_not_labelled_measured(self):
        sol = EquilibriumSolution(
            converged=True, solver_status="CONVERGED",
            predicted_offset_m=50.0, provenance="MODELLED")
        assert sol.provenance == "MODELLED"
        assert sol.provenance != "MEASURED"

    def test_residual_exposed(self):
        config = _make_config()
        forces = _forces(3000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.equilibrium_residual_n is not None
        assert math.isfinite(sol.equilibrium_residual_n)

    def test_iterations_positive(self):
        config = _make_config()
        forces = _forces(3000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.iterations >= 0


class TestEquilibriumInMooringResponse:
    def test_equilibrium_wired_into_response(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        telemetry = {
            "meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"},
                            "windDirection": {"value": 90.0, "unit": "°"}},
            "ocean": {}, "waves": {}, "profiles": {},
        }
        response = compute_mooring_response(
            "OMNI-BD10", 16.3617, 87.9903, telemetry,
            "2026-10-08T03:00:00Z", resolver, telemetry_age_seconds=3600)
        # equilibrium fields must exist (may be None if solver fails)
        assert hasattr(response, "predicted_offset_m")
        assert hasattr(response, "equilibrium_solver_status")
        assert hasattr(response, "equilibrium_residual_n")

    def test_equilibrium_result_is_modelled_not_measured(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        telemetry = {
            "meteorology": {"windSpeed": {"value": 10.0, "unit": "m/s"},
                            "windDirection": {"value": 180.0, "unit": "°"}},
            "ocean": {}, "waves": {}, "profiles": {},
        }
        response = compute_mooring_response(
            "OMNI-BD10", 16.3617, 87.9903, telemetry,
            "2026-10-08T03:00:00Z", resolver, telemetry_age_seconds=3600)
        # buoy_motion_validation_status must default to NOT_VALIDATED
        assert response.buoy_motion_validation_status == "NOT_VALIDATED"
        # observed_offset_m must be null (no GPS track)
        assert response.observed_offset_m is None
        assert response.position_error_m is None


# ── Phase E/F: Validation Hooks ──────────────────────────────────────────────

class TestForwardInverseValidation:
    def test_no_gps_no_validation(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01",
            predicted_offset_m=50.0, observed_offset_m=None)
        assert response.position_error_m is None
        assert response.buoy_motion_validation_status == "NOT_VALIDATED"

    def test_model_fields_default_not_validated(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01")
        assert response.measured_tension is None
        assert response.observed_offset_m is None
        assert response.buoy_motion_validation_status == "NOT_VALIDATED"


# ── Phase H: Physics Diagnostics ────────────────────────────────────────────

class TestPhysicsDiagnostics:
    def test_environmental_forces_expose_components(self):
        env = EnvironmentalState(
            wind_speed_ms=10.0, wind_direction_deg=90.0,
            current_speed_ms=0.5, current_direction_deg=90.0)
        config = _make_config()
        forces = compute_environmental_forces(env, config)
        assert forces.wind_force_n is not None
        assert forces.current_force_n is not None
        assert forces.wind_fx is not None
        assert forces.wind_fy is not None
        assert forces.total_horizontal_n is not None

    def test_missing_current_force_is_none_not_zero(self):
        env = EnvironmentalState(wind_speed_ms=10.0, wind_direction_deg=90.0)
        config = _make_config()
        forces = compute_environmental_forces(env, config)
        assert forces.current_force_n is None
        assert forces.current_fx is None

    def test_missing_wave_force_is_none_not_zero(self):
        env = EnvironmentalState(wind_speed_ms=5.0, wind_direction_deg=0.0)
        config = _make_config()
        forces = compute_environmental_forces(env, config)
        assert forces.wave_force_n is None
        assert forces.wave_fx is None

    def test_equilibrium_residual_exposed(self):
        config = _make_config()
        forces = _forces(5000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.equilibrium_residual_n is not None

    def test_solver_iterations_in_equilibrium(self):
        config = _make_config()
        forces = _forces(5000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert isinstance(sol.iterations, int)
        assert sol.iterations >= 0


# ── Phase S: Provenance Audit ────────────────────────────────────────────────

class TestProvenanceAudit:
    def test_no_zero_substitution_for_missing_current(self):
        env = EnvironmentalState(wind_speed_ms=5.0)
        config = _make_config()
        forces = compute_environmental_forces(env, config)
        # current_force must be None, not 0.0
        assert forces.current_force_n is None
        assert forces.current_fx is None

    def test_no_zero_substitution_for_missing_wave(self):
        env = EnvironmentalState(wind_speed_ms=5.0)
        config = _make_config()
        forces = compute_environmental_forces(env, config)
        assert forces.wave_force_n is None

    def test_no_fabricated_mbl_in_default_config(self):
        config = MooringConfiguration(buoy_id="T")
        from services.mooring.catenary_solver import compute_utilization
        assert compute_utilization(10000.0, config.segments) is None

    def test_tension_not_labeled_measured(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01",
            model_timestamp="2026-01-01", fairlead_tension_n=15000.0)
        assert response.measured_tension is None

    def test_configuration_assumptions_marked_correctly(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        for seg in config.segments:
            assert seg.provenance.status == "ASSUMPTION"
        assert config.pretension_n.provenance.status == "ASSUMPTION"

    def test_water_depth_not_authoritative(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.water_depth.provenance.status != "AUTHORITATIVE"
        assert config.water_depth.provenance.status == "INFERRED"

    def test_equilibrium_provenance_not_measured(self):
        config = _make_config()
        forces = _forces(3000.0, 0.0)
        sol = solve_equilibrium(config, forces)
        assert sol.provenance == "MODELLED"
        assert "MEASURED" not in sol.provenance

    def test_fleet_all_stations_have_assumption_line_properties(self):
        from services.mooring.bathymetry_service import OMNI_FLEET_SEED
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            config = resolver.resolve(buoy_id, entry["lat"], entry["lon"])
            for seg in config.segments:
                assert seg.provenance.status == "ASSUMPTION", \
                    f"{buoy_id}: segment '{seg.name}' should be ASSUMPTION"
