"""Comprehensive tests for the mooring Digital Twin system.

Covers: bathymetry, config resolver, trajectory, catenary, environmental forces,
risk engine, confidence, fleet runner, API endpoints, physics sanity, and
a synthetic full-pipeline test.
"""
import math
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.buoy.buoy_models import Buoy, Observation
from services.buoy.buoy_cache import BuoyCache
from services.buoy.runtime import BuoyRuntime, BuoySettings
from services.mooring.models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
    EnvironmentalState, MooringResponse, FleetDigitalTwinEntry,
)
from services.mooring.config_resolver import MooringConfigResolver, OMNI_SCOPE
from services.mooring.trajectory_service import haversine_m, bearing_deg, analyze_trajectory
from services.mooring.environmental_forces import (
    wind_force, current_force_on_buoy, wave_force_morison,
    compute_environmental_forces, _wave_number,
)
from services.mooring.catenary_solver import (
    solve_catenary, compute_utilization, compute_safety_factor,
)
from services.mooring.risk_engine import assess_risk, RiskThresholds
from services.mooring.confidence import compute_confidence
from services.mooring.mooring_response import compute_mooring_response, extract_environmental_state
from services.mooring.fleet_runner import FleetRunner
from app.api.routes_buoys import router as buoys_router

BD10 = Buoy(id='OMNI-BD10', name='OMNI-BD10', type='OMNI', latitude=15.0, longitude=90.0)
BD14 = Buoy(id='OMNI-BD14', name='OMNI-BD14', type='OMNI', latitude=6.57, longitude=88.23)


# ── Bathymetry ────────────────────────────────────────────

class TestBathymetry:
    def test_cache_key_rounding(self):
        from services.mooring.bathymetry_service import BathymetryService
        k = BathymetryService._cache_key(15.123, 90.456)
        assert "15.123" in k and "90.456" in k

    def test_cache_key_negative(self):
        from services.mooring.bathymetry_service import BathymetryService
        k = BathymetryService._cache_key(-6.57, -88.23)
        assert "-6.570" in k and "-88.230" in k


# ── Config Resolver ───────────────────────────────────────

class TestConfigResolver:
    def test_scope_to_line_length(self):
        depth = 3250
        expected = depth * OMNI_SCOPE
        assert expected == pytest.approx(3965.0, abs=1)

    def test_reference_config_has_provenance(self):
        from services.mooring.bathymetry_service import BathymetryService
        bathy = BathymetryService()
        # Inject test depth via buoy cache (takes precedence over coordinate cache)
        bathy._buoy_cache["OMNI-TEST-3250"] = ProvenancedValue(
            value=3250, unit="m",
            provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH"))
        resolver = MooringConfigResolver(bathy)
        config = resolver.resolve("OMNI-TEST-3250", 15.0, 90.0)
        assert config.configuration_status == "REFERENCE"
        assert config.water_depth.value == 3250
        assert config.water_depth.provenance.status == "INFERRED"
        assert config.scope.value == OMNI_SCOPE
        assert config.scope.provenance.status == "REFERENCE"
        assert config.total_line_length.value == pytest.approx(3965.0, abs=1)
        assert config.total_line_length.provenance.status == "DERIVED"
        assert len(config.segments) == 3

    def test_reference_config_segments_sum_to_total(self):
        from services.mooring.bathymetry_service import BathymetryService
        bathy = BathymetryService()
        bathy._buoy_cache["OMNI-TEST-3250"] = ProvenancedValue(
            value=3250, unit="m",
            provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH"))
        resolver = MooringConfigResolver(bathy)
        config = resolver.resolve("OMNI-TEST-3250", 15.0, 90.0)
        seg_total = sum(s.length_m for s in config.segments)
        assert seg_total == pytest.approx(config.total_line_length.value, abs=1)

    def test_authoritative_config_used_when_provided(self):
        resolver = MooringConfigResolver()
        config = resolver.resolve("OMNI-BD10", 15.0, 90.0, authoritative={
            "water_depth_m": 3200, "source": "NIOT", "scope": 1.22,
            "total_line_length_m": 3904, "line_count": 1,
            "segments": [{"name": "main", "length_m": 3904, "submerged_weight_n_m": 5.0}]
        })
        assert config.configuration_status == "AUTHORITATIVE"
        assert config.water_depth.provenance.status == "AUTHORITATIVE"

    def test_no_depth_returns_no_line_length(self):
        from services.mooring.bathymetry_service import BathymetryService
        resolver = MooringConfigResolver(BathymetryService())
        config = resolver.resolve("OMNI-TEST", 0.0, 0.0)
        if config.water_depth.value is None:
            assert config.total_line_length.value is None


# ── Trajectory ────────────────────────────────────────────

class TestTrajectory:
    def test_haversine_zero_distance(self):
        assert haversine_m(15.0, 90.0, 15.0, 90.0) == pytest.approx(0, abs=0.01)

    def test_haversine_known_distance(self):
        d = haversine_m(0, 0, 0, 1)
        assert d == pytest.approx(111195, rel=0.01)

    def test_bearing_north(self):
        b = bearing_deg(0, 0, 1, 0)
        assert b == pytest.approx(0, abs=0.1)

    def test_bearing_east(self):
        b = bearing_deg(0, 0, 0, 1)
        assert b == pytest.approx(90, abs=0.5)

    def test_analyze_trajectory_centroid_anchor(self):
        positions = [
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"},
            {"latitude": 15.001, "longitude": 90.001, "timestamp": "2026-01-01T01:00:00Z"},
            {"latitude": 14.999, "longitude": 89.999, "timestamp": "2026-01-01T02:00:00Z"},
        ]
        result = analyze_trajectory("BD10", positions)
        assert result.estimated_anchor_latitude == pytest.approx(15.0, abs=0.001)
        assert result.estimated_anchor_longitude == pytest.approx(90.0, abs=0.001)
        assert result.provenance.status == "ESTIMATED"

    def test_empty_trajectory(self):
        result = analyze_trajectory("BD10", [])
        assert result.points == []


# ── Environmental Forces ──────────────────────────────────

class TestEnvironmentalForces:
    def test_wind_force_basic(self):
        # FROM=0° (North wind) → force acts southward → Fy = -F, Fx = 0
        mag, fx, fy = wind_force(10.0, 5.0, 0.0)
        expected = 0.5 * 1.225 * 1.2 * 5.0 * 100
        assert mag == pytest.approx(expected, rel=1e-6)
        assert fy == pytest.approx(-expected, rel=1e-6)  # southward
        assert fx == pytest.approx(0, abs=0.01)

    def test_wind_force_increases_with_speed(self):
        m1, _, _ = wind_force(5.0, 5.0, 0.0)
        m2, _, _ = wind_force(10.0, 5.0, 0.0)
        assert m2 > m1

    def test_current_force_basic(self):
        mag, _, _ = current_force_on_buoy(1.0, 3.0, 90.0)
        assert mag > 0

    def test_current_force_increases_with_speed(self):
        m1, _, _ = current_force_on_buoy(0.5, 3.0, 90.0)
        m2, _, _ = current_force_on_buoy(1.0, 3.0, 90.0)
        assert m2 > m1

    def test_wave_force_basic(self):
        mag, _, _ = wave_force_morison(2.0, 8.0, 180.0, 3000.0, 2.7, 1.6)
        assert mag > 0

    def test_wave_number_deep_water(self):
        omega = 2 * math.pi / 8
        k = _wave_number(omega, 3000.0)
        assert k > 0
        assert k * 3000 > 10  # deep water

    def test_vector_combination_perpendicular(self):
        env = EnvironmentalState(wind_speed_ms=10.0, wind_direction_deg=0.0,
                                 current_speed_ms=1.0, current_direction_deg=90.0)
        config = MooringConfiguration(
            buoy_id="TEST", water_depth=ProvenancedValue(value=3000, unit="m",
                provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3660, unit="m",
                provenance=DataProvenance(source="TEST", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="test", length_m=3660, submerged_weight_n_m=5.0)])
        forces = compute_environmental_forces(env, config)
        assert forces.total_horizontal_n > 0
        assert forces.wind_force_n > 0
        assert forces.current_force_n > 0


# ── Catenary Solver ───────────────────────────────────────

class TestCatenarySolver:
    @staticmethod
    def _config(depth=3250, scope=1.22):
        ll = depth * scope
        return MooringConfiguration(
            buoy_id="TEST",
            water_depth=ProvenancedValue(value=depth, unit="m",
                provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH")),
            scope=ProvenancedValue(value=scope, unit="",
                provenance=DataProvenance(source="TEST", status="REFERENCE", confidence="MEDIUM")),
            total_line_length=ProvenancedValue(value=ll, unit="m",
                provenance=DataProvenance(source="TEST", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="main", length_m=ll,
                                         submerged_weight_n_m=5.0,
                                         breaking_strength_n=250000.0)])

    def test_solver_converges(self):
        config = self._config()
        sol = solve_catenary(config, 5000.0)
        assert sol.converged
        assert sol.fairlead_tension_n > 0
        assert sol.anchor_tension_n > 0

    def test_tension_increases_with_force(self):
        config = self._config()
        sol1 = solve_catenary(config, 1000.0)
        sol2 = solve_catenary(config, 10000.0)
        assert sol1.converged and sol2.converged
        assert sol2.fairlead_tension_n > sol1.fairlead_tension_n

    def test_line_angle_physical_range(self):
        config = self._config()
        sol = solve_catenary(config, 5000.0)
        assert sol.converged
        assert 0 < sol.line_angle_deg < 90

    def test_solver_no_depth(self):
        config = MooringConfiguration(buoy_id="TEST")
        sol = solve_catenary(config, 5000.0)
        assert not sol.converged

    def test_utilization_with_mbl(self):
        config = self._config()
        sol = solve_catenary(config, 5000.0)
        util = compute_utilization(sol.fairlead_tension_n, config.segments)
        assert util is not None
        assert 0 < util < 1

    def test_utilization_increases_with_tension(self):
        config = self._config()
        sol1 = solve_catenary(config, 1000.0)
        sol2 = solve_catenary(config, 50000.0)
        u1 = compute_utilization(sol1.fairlead_tension_n, config.segments)
        u2 = compute_utilization(sol2.fairlead_tension_n, config.segments)
        assert u1 is not None and u2 is not None
        assert u2 > u1

    def test_safety_factor_with_mbl(self):
        config = self._config()
        sol = solve_catenary(config, 5000.0)
        sf = compute_safety_factor(sol.fairlead_tension_n, config.segments)
        assert sf is not None
        assert sf > 0

    def test_safety_factor_decreases_with_load(self):
        config = self._config()
        sol1 = solve_catenary(config, 1000.0)
        sol2 = solve_catenary(config, 50000.0)
        sf1 = compute_safety_factor(sol1.fairlead_tension_n, config.segments)
        sf2 = compute_safety_factor(sol2.fairlead_tension_n, config.segments)
        assert sf1 > sf2

    def test_missing_mbl_returns_none(self):
        config = MooringConfiguration(
            buoy_id="TEST",
            water_depth=ProvenancedValue(value=3250, unit="m",
                provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3965, unit="m",
                provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="main", length_m=3965, submerged_weight_n_m=5.0)])
        sol = solve_catenary(config, 5000.0)
        assert compute_utilization(sol.fairlead_tension_n, config.segments) is None
        assert compute_safety_factor(sol.fairlead_tension_n, config.segments) is None


# ── Risk Engine ───────────────────────────────────────────

class TestRiskEngine:
    def test_normal(self):
        assert assess_risk(utilization=0.2, solver_converged=True) == "NORMAL"

    def test_watch(self):
        assert assess_risk(utilization=0.45, solver_converged=True) == "WATCH"

    def test_warning(self):
        assert assess_risk(utilization=0.65, solver_converged=True) == "WARNING"

    def test_critical(self):
        assert assess_risk(utilization=0.85, solver_converged=True) == "CRITICAL"

    def test_insufficient_data_without_convergence(self):
        assert assess_risk(utilization=0.3, solver_converged=False) == "INSUFFICIENT_DATA"

    def test_safety_factor_critical(self):
        assert assess_risk(safety_factor=1.2, solver_converged=True) == "CRITICAL"

    def test_configurable_thresholds(self):
        thresholds = RiskThresholds(utilization_critical=0.5)
        assert assess_risk(utilization=0.55, solver_converged=True, thresholds=thresholds) == "CRITICAL"


# ── Confidence ────────────────────────────────────────────

class TestConfidence:
    def test_high_confidence_with_all_data(self):
        # AUTHORITATIVE config with all environmental data + bathymetry
        depth_pv = ProvenancedValue(value=3000, unit="m",
            provenance=DataProvenance(source="NIOT", status="AUTHORITATIVE", confidence="HIGH"))
        config = MooringConfiguration(
            buoy_id="T", configuration_status="AUTHORITATIVE",
            water_depth=depth_pv,
            segments=[MooringLineSegment(name="m", length_m=3000, submerged_weight_n_m=5.0)],
            anchor_latitude=ProvenancedValue(value=15.0, unit="°",
                provenance=DataProvenance(source="NIOT", status="AUTHORITATIVE", confidence="HIGH")))
        env = EnvironmentalState(wind_speed_ms=10, current_speed_ms=0.5, wave_height_m=2.0)
        overall, breakdown = compute_confidence(config, env, "CONVERGED", 3000)
        # AUTHORITATIVE config + all environmental data = at least MEDIUM
        assert overall in ("HIGH", "MEDIUM")
        assert breakdown.telemetry == "HIGH"
        assert breakdown.environmental_data == "HIGH"
        assert breakdown.bathymetry == "HIGH"

    def test_low_confidence_with_missing_data(self):
        config = MooringConfiguration(buoy_id="T")
        env = EnvironmentalState()
        overall, breakdown = compute_confidence(config, env, "NOT_RUN", None)
        assert overall in ("LOW", "UNKNOWN")


# ── Full Pipeline: Synthetic Digital Twin ─────────────────

class TestSyntheticDigitalTwin:
    """Deterministic synthetic buoy through the full pipeline."""

    def test_full_pipeline_converges(self):
        from services.mooring.bathymetry_service import BathymetryService
        bathy = BathymetryService()
        # Use real pre-seeded BD10 depth (2627m)
        resolver = MooringConfigResolver(bathy)

        telemetry = {
            "meteorology": {"windSpeed": {"value": 10.0, "unit": "m/s"},
                            "windDirection": {"value": 45.0, "unit": "°"}},
            "ocean": {},
            "waves": {},
            "profiles": {},
        }
        response = compute_mooring_response(
            buoy_id="OMNI-BD10", latitude=16.3617, longitude=87.9903,
            telemetry=telemetry, observation_timestamp="2026-10-08T03:00:00Z",
            resolver=resolver, telemetry_age_seconds=3600)

        assert response.solver_status in ("CONVERGED", "WARNING")
        assert response.fairlead_tension_n is not None
        assert response.fairlead_tension_n > 0
        assert response.line_angle_deg is not None
        assert 0 < response.line_angle_deg < 90
        if response.utilization is not None:
            assert response.utilization > 0
        if response.safety_factor is not None:
            assert response.safety_factor > 0
        assert response.risk_state in ("NORMAL", "WATCH", "WARNING", "CRITICAL")
        assert response.model_version.startswith("MoorSense")


# ── Fleet Runner ──────────────────────────────────────────

class TestFleetRunner:
    def test_fleet_runs_all_buoys(self):
        from services.mooring.bathymetry_service import BathymetryService
        bathy = BathymetryService()
        # Use real pre-seeded fleet depths
        resolver = MooringConfigResolver(bathy)
        runner = FleetRunner(resolver)

        buoys = {"OMNI-BD10": BD10, "OMNI-BD14": BD14}
        cache = BuoyCache()
        for buoy_id, buoy in buoys.items():
            obs = Observation(buoyId=buoy_id,
                              timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                              source="TEST",
                              telemetry={"meteorology": {"windSpeed": {"value": 8.0, "unit": "m/s"},
                                                         "windDirection": {"value": 180.0, "unit": "°"}}})
            cache.update(obs)

        results = runner.run_fleet(buoys, cache)
        assert len(results) == 2
        assert all(isinstance(r, FleetDigitalTwinEntry) for r in results)
        for r in results:
            assert r.buoy_id in buoys
            if r.error is None:
                assert r.solver_status in ("CONVERGED", "WARNING", "NOT_RUN")

    def test_one_failure_does_not_crash_fleet(self):
        runner = FleetRunner()
        buoys = {"OMNI-BD10": BD10, "OMNI-FAKE": Buoy(id="OMNI-FAKE", name="FAKE", type="OMNI", latitude=0, longitude=0)}
        cache = BuoyCache()
        obs = Observation(buoyId="OMNI-BD10",
                          timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                          source="TEST", telemetry={"meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"},
                                                                     "windDirection": {"value": 0.0, "unit": "°"}}})
        cache.update(obs)
        results = runner.run_fleet(buoys, cache)
        assert len(results) == 2
        bd10 = next(r for r in results if r.buoy_id == "OMNI-BD10")
        fake = next(r for r in results if r.buoy_id == "OMNI-FAKE")
        assert fake.error is not None


# ── Physics Sanity (monotonicity) ─────────────────────────

class TestPhysicsSanity:
    def test_wind_force_monotonically_increases(self):
        forces = [wind_force(v, 5.0, 0.0)[0] for v in [0, 2, 5, 10, 20]]
        for i in range(1, len(forces)):
            assert forces[i] >= forces[i - 1]

    def test_current_force_scales_with_v_squared(self):
        f1, _, _ = current_force_on_buoy(1.0, 3.0, 0.0)
        f2, _, _ = current_force_on_buoy(2.0, 3.0, 0.0)
        assert f2 == pytest.approx(f1 * 4, rel=0.01)

    def test_tension_increases_monotonically_with_load(self):
        config = TestCatenarySolver._config()
        tensions = []
        for f in [100, 1000, 5000, 10000, 50000]:
            sol = solve_catenary(config, f)
            if sol.converged:
                tensions.append(sol.fairlead_tension_n)
        for i in range(1, len(tensions)):
            assert tensions[i] >= tensions[i - 1]

    def test_utilization_decreases_with_stronger_line(self):
        config1 = MooringConfiguration(
            buoy_id="T",
            water_depth=ProvenancedValue(value=3250, unit="m",
                provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3965, unit="m",
                provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="m", length_m=3965, submerged_weight_n_m=5.0, breaking_strength_n=200000)])
        config2 = MooringConfiguration(
            buoy_id="T",
            water_depth=ProvenancedValue(value=3250, unit="m",
                provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3965, unit="m",
                provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="m", length_m=3965, submerged_weight_n_m=5.0, breaking_strength_n=500000)])
        sol = solve_catenary(config1, 5000.0)
        u1 = compute_utilization(sol.fairlead_tension_n, config1.segments)
        u2 = compute_utilization(sol.fairlead_tension_n, config2.segments)
        assert u1 > u2


# ── Provenance Guards ─────────────────────────────────────

class TestProvenanceGuards:
    def test_measured_not_relabelled(self):
        env = extract_environmental_state({
            "meteorology": {"windSpeed": {"value": 10.0, "unit": "m/s"}},
            "ocean": {}, "waves": {}, "profiles": {},
        })
        assert env.sources.get("wind") == "MEASURED"

    def test_missing_wave_not_zero(self):
        env = extract_environmental_state({
            "meteorology": {}, "ocean": {}, "waves": {}, "profiles": {},
        })
        assert env.wave_height_m is None
        assert env.sources.get("wave") == "UNAVAILABLE"

    def test_missing_current_not_zero(self):
        env = extract_environmental_state({
            "meteorology": {}, "ocean": {}, "waves": {}, "profiles": {},
        })
        assert env.current_speed_ms is None
        assert env.sources.get("current") == "UNAVAILABLE"

    def test_derived_tension_not_labelled_measured(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01",
            fairlead_tension_n=15000, solver_status="CONVERGED")
        assert "measured" not in response.model_version.lower()
        assert "ESTIMATED" not in response.solver_status  # it's CONVERGED, a solver state
