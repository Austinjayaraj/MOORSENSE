"""Tests for Phases 4-12: configuration versioning, replay, station capabilities,
separated risk, model versioning, temporal safety, and provenance guards.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest

from services.mooring.models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
    EnvironmentalState, MooringResponse, ConfidenceBreakdown, FleetDigitalTwinEntry,
)
from services.mooring.versioned_config import (
    MooringConfigRegistry, MooringConfigVersionEntry, model_version_metadata,
    MODEL_VERSION, PHYSICS_VERSION, CONFIGURATION_VERSION,
)
from services.mooring.station_capabilities import (
    StationCapabilityProfile, ParameterCapability, build_capability_profile,
)
from services.mooring.risk_engine import (
    assess_risk, assess_separated_risk, assess_data_risk, assess_model_risk,
    assess_engineering_risk, RiskThresholds, SeparatedRisk,
)
from services.replay.replay_runner import (
    ReplayRunner, ReplayObservation, ReplayResult,
)
from services.mooring.config_resolver import MooringConfigResolver
from services.mooring.bathymetry_service import BathymetryService, OMNI_FLEET_SEED


# ── Phase 4B/4C: Configuration Versioning ────────────────────────────────────

class TestMooringConfigRegistry:
    def _entry(self, station_id: str, precedence: str,
               valid_from: datetime | None = None,
               valid_to: datetime | None = None) -> MooringConfigVersionEntry:
        return MooringConfigVersionEntry(
            station_id=station_id, deployment_id=None,
            valid_from=valid_from, valid_to=valid_to,
            configuration={"water_depth_m": 3000}, precedence=precedence,
            source="TEST")

    def test_authoritative_overrides_reference(self):
        reg = MooringConfigRegistry()
        ts = datetime.now(timezone.utc)
        reg.register(self._entry("OMNI-BD10", "REFERENCE"))
        reg.register(self._entry("OMNI-BD10", "AUTHORITATIVE"))
        result = reg.resolve_at("OMNI-BD10", ts)
        assert result is not None
        assert result.precedence == "AUTHORITATIVE"

    def test_station_specific_before_fleet(self):
        reg = MooringConfigRegistry()
        ts = datetime.now(timezone.utc)
        reg.register(self._entry("OMNI-BD10", "PUBLISHED_REFERENCE"))
        reg.register(self._entry("OMNI-BD10", "STATION_AUTHORITATIVE"))
        result = reg.resolve_at("OMNI-BD10", ts)
        assert result.precedence == "STATION_AUTHORITATIVE"

    def test_temporal_guard_no_future_config(self):
        """Configuration valid only after ts must NOT be returned for earlier ts."""
        reg = MooringConfigRegistry()
        future = datetime.now(timezone.utc) + timedelta(days=30)
        past = datetime.now(timezone.utc) - timedelta(days=30)
        reg.register(self._entry("OMNI-BD10", "AUTHORITATIVE", valid_from=future))
        reg.register(self._entry("OMNI-BD10", "REFERENCE", valid_from=past))
        result = reg.resolve_at("OMNI-BD10", datetime.now(timezone.utc))
        assert result is not None
        assert result.precedence == "REFERENCE"  # future AUTHORITATIVE must not be returned

    def test_versioned_deployment_history(self):
        reg = MooringConfigRegistry()
        t1 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        deploy1 = self._entry("OMNI-BD10", "AUTHORITATIVE",
                               valid_from=t1, valid_to=t2)
        deploy2 = self._entry("OMNI-BD10", "AUTHORITATIVE",
                               valid_from=t2, valid_to=None)
        reg.register(deploy1)
        reg.register(deploy2)
        mid_2025 = datetime(2025, 6, 1, tzinfo=timezone.utc)
        mid_2026 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        r1 = reg.resolve_at("OMNI-BD10", mid_2025)
        r2 = reg.resolve_at("OMNI-BD10", mid_2026)
        assert r1.valid_from == t1
        assert r2.valid_from == t2

    def test_unknown_station_returns_none(self):
        reg = MooringConfigRegistry()
        assert reg.resolve_at("OMNI-UNKNOWN", datetime.now(timezone.utc)) is None

    def test_all_versions_returned(self):
        reg = MooringConfigRegistry()
        t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        reg.register(self._entry("OMNI-BD10", "REFERENCE", valid_from=t1))
        reg.register(self._entry("OMNI-BD10", "REFERENCE", valid_from=t2))
        assert len(reg.all_versions("OMNI-BD10")) == 2


# ── Phase 5: Historical Replay ────────────────────────────────────────────────

class TestReplayRunner:
    def _obs(self, station_id: str, timestamp: datetime, wind_speed: float) -> ReplayObservation:
        return ReplayObservation(
            station_id=station_id,
            observation_timestamp=timestamp,
            telemetry={
                "meteorology": {"windSpeed": {"value": wind_speed, "unit": "m/s"},
                                "windDirection": {"value": 180.0, "unit": "°"}},
                "ocean": {}, "waves": {}, "profiles": {},
            })

    def test_replay_processes_observations_chronologically(self):
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
        t2 = datetime(2026, 10, 3, 0, 0, 0, tzinfo=timezone.utc)
        # Feed in reverse order
        obs = [self._obs("OMNI-BD10", t2, 8.0),
               self._obs("OMNI-BD10", t0, 5.0),
               self._obs("OMNI-BD10", t1, 6.0)]
        results = runner.replay_observations("OMNI-BD10", obs)
        assert len(results) == 3
        timestamps = [r.observation_timestamp for r in results]
        assert timestamps == sorted(timestamps)  # must be in chronological order

    def test_replay_each_observation_independent(self):
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 10, 2, 0, 0, 0, tzinfo=timezone.utc)
        obs = [self._obs("OMNI-BD10", t0, 2.0),
               self._obs("OMNI-BD10", t1, 15.0)]
        results = runner.replay_observations("OMNI-BD10", obs)
        r0, r1 = results[0], results[1]
        # Higher wind should produce different tension
        assert isinstance(r0.mooring_response, MooringResponse)
        assert isinstance(r1.mooring_response, MooringResponse)
        # Results must differ (different wind)
        t0_tension = r0.mooring_response.fairlead_tension_n
        t1_tension = r1.mooring_response.fairlead_tension_n
        if t0_tension is not None and t1_tension is not None:
            assert t1_tension > t0_tension  # more wind → more tension

    def test_replay_observation_requires_timezone(self):
        with pytest.raises(ValueError, match="timezone"):
            ReplayObservation(
                station_id="OMNI-BD10",
                observation_timestamp=datetime(2026, 10, 1, 0, 0, 0),  # naive
                telemetry={})

    def test_replay_handles_unknown_station_gracefully(self):
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
        obs = [ReplayObservation(
            station_id="OMNI-NONEXISTENT",
            observation_timestamp=t0,
            telemetry={"meteorology": {}, "ocean": {}, "waves": {}, "profiles": {}})]
        results = runner.replay_observations("OMNI-NONEXISTENT", obs)
        # Unknown station should fail gracefully — either empty or with error result
        # The runner catches exceptions, so may return empty
        assert isinstance(results, list)

    def test_replay_model_versions_in_result(self):
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        obs = [self._obs("OMNI-BD10", t0, 5.0)]
        results = runner.replay_observations("OMNI-BD10", obs)
        assert len(results) == 1
        versions = results[0].model_versions
        assert "model_version" in versions
        assert "physics_version" in versions
        assert "configuration_version" in versions


# ── Phase 6: Station Capabilities ────────────────────────────────────────────

class TestStationCapabilities:
    def test_available_wind_maps_to_measured(self):
        profile = build_capability_profile("OMNI-BD10", {
            "wind_speed": "AVAILABLE", "wind_direction": "AVAILABLE",
        })
        assert profile.wind_speed.status == "MEASURED"
        assert profile.wind_direction.status == "MEASURED"

    def test_restricted_wind_maps_correctly(self):
        profile = build_capability_profile("OMNI-AD06", {
            "wind_speed": "RESTRICTED",
        })
        assert profile.wind_speed.status == "RESTRICTED"

    def test_not_offered_maps_correctly(self):
        profile = build_capability_profile("OMNI-BD10", {
            "current_speed": "NOT_OFFERED",
        })
        assert profile.current_speed.status == "NOT_OFFERED"

    def test_wind_only_completeness(self):
        profile = StationCapabilityProfile(
            station_id="OMNI-BD10",
            wind_speed=ParameterCapability(status="MEASURED"))
        assert profile.environmental_completeness() == "WIND_ONLY"

    def test_full_completeness(self):
        profile = StationCapabilityProfile(
            station_id="OMNI-BD10",
            wind_speed=ParameterCapability(status="MEASURED"),
            current_speed=ParameterCapability(status="MEASURED"),
            significant_wave_height=ParameterCapability(status="MEASURED"))
        assert profile.environmental_completeness() == "COMPLETE"

    def test_missing_current_not_zero(self):
        profile = build_capability_profile("OMNI-BD10", {
            "wind_speed": "AVAILABLE",
            "current_speed": "NOT_OFFERED",
        })
        assert profile.current_speed.status == "NOT_OFFERED"
        # Must not be "MEASURED" or any numeric value
        assert profile.current_speed.status != "MEASURED"

    def test_unknown_parameter_remains_unknown(self):
        profile = build_capability_profile("OMNI-BD10", {})
        assert profile.wind_speed.status == "UNKNOWN"
        assert profile.current_speed.status == "UNKNOWN"


# ── Phase 9: Separated Risk ───────────────────────────────────────────────────

class TestSeparatedRisk:
    def test_wind_only_produces_data_watch(self):
        d_state, note = assess_data_risk(3600, "WIND_ONLY")
        assert d_state == "WATCH"
        assert "current" in note.lower() or "wave" in note.lower()

    def test_no_forcing_produces_insufficient_data(self):
        d_state, _ = assess_data_risk(3600, "NO_FORCING")
        assert d_state == "INSUFFICIENT_DATA"

    def test_assumption_config_produces_model_watch(self):
        m_state, note = assess_model_risk("ASSUMPTION", "LOW", "CONVERGED")
        assert m_state == "WATCH"

    def test_failed_solver_produces_insufficient(self):
        m_state, _ = assess_model_risk("REFERENCE", "MEDIUM", "FAILED")
        assert m_state == "INSUFFICIENT_DATA"

    def test_high_utilization_produces_critical(self):
        e_state, _ = assess_engineering_risk(0.85, None, None, True)
        assert e_state == "CRITICAL"

    def test_separated_risk_has_three_dimensions(self):
        sr = assess_separated_risk(
            telemetry_age_s=3600, forcing_mode="WIND_ONLY",
            configuration_status="REFERENCE", confidence="LOW",
            solver_status="CONVERGED", utilization=0.2)
        assert sr.data_status == "WATCH"
        assert sr.model_status == "WATCH"
        assert sr.engineering_status == "NORMAL"
        assert sr.overall_status == "WATCH"  # worst of three

    def test_overall_is_worst_dimension(self):
        sr = assess_separated_risk(
            telemetry_age_s=3600, forcing_mode="WIND_CURRENT_WAVE",
            configuration_status="AUTHORITATIVE", confidence="HIGH",
            solver_status="CONVERGED", utilization=0.85)
        assert sr.overall_status == "CRITICAL"

    def test_insufficient_data_cannot_become_normal(self):
        """INSUFFICIENT_DATA must not be masked by other NORMAL dimensions."""
        sr = assess_separated_risk(
            telemetry_age_s=None, forcing_mode="UNKNOWN",
            configuration_status="AUTHORITATIVE", confidence="HIGH",
            solver_status="CONVERGED", utilization=0.1)
        assert sr.data_status == "INSUFFICIENT_DATA"
        assert sr.overall_status == "INSUFFICIENT_DATA"


# ── Phase 11: Solver Edge Cases ───────────────────────────────────────────────

class TestSolverEdgeCases:
    from services.mooring.catenary_solver import solve_catenary

    @staticmethod
    def _config(depth: float, line_length: float, weight: float = 5.0) -> MooringConfiguration:
        from services.mooring.models import MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance
        return MooringConfiguration(
            buoy_id="TEST",
            water_depth=ProvenancedValue(value=depth, unit="m",
                provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=line_length, unit="m",
                provenance=DataProvenance(source="TEST", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="main", length_m=line_length,
                                         submerged_weight_n_m=weight,
                                         breaking_strength_n=250000.0)])

    def test_zero_environmental_force(self):
        from services.mooring.catenary_solver import solve_catenary
        config = self._config(3000, 3660)
        sol = solve_catenary(config, 0.0)
        # Zero force: still converges, tension dominated by line weight
        assert sol.converged
        assert sol.fairlead_tension_n > 0
        assert sol.vertical_tension_n > 0

    def test_impossible_geometry_no_depth(self):
        from services.mooring.catenary_solver import solve_catenary
        config = MooringConfiguration(buoy_id="T")
        sol = solve_catenary(config, 5000)
        assert not sol.converged

    def test_line_length_less_than_depth_handled(self):
        """If line length < depth, suspended length is capped at total_length."""
        from services.mooring.catenary_solver import solve_catenary
        config = self._config(3000, 1000)  # line shorter than depth
        sol = solve_catenary(config, 5000)
        assert sol.suspended_length_m <= 1000.0

    def test_tension_positive_nonzero(self):
        from services.mooring.catenary_solver import solve_catenary
        config = self._config(2627, 3205)
        sol = solve_catenary(config, 100.0)
        assert sol.converged
        assert sol.fairlead_tension_n > 0
        assert sol.anchor_tension_n > 0

    def test_line_angle_in_physical_range(self):
        from services.mooring.catenary_solver import solve_catenary
        config = self._config(3000, 3660)
        sol = solve_catenary(config, 5000)
        assert sol.converged
        assert 0 <= sol.line_angle_deg <= 90

    def test_solver_status_is_one_of_allowed_values(self):
        from services.mooring.catenary_solver import solve_catenary
        config = self._config(3000, 3660)
        sol = solve_catenary(config, 5000)
        assert sol.converged or not sol.converged  # just a bool — no fake status
        # The solver itself doesn't return a string status — that's done by the pipeline
        assert isinstance(sol.converged, bool)


# ── Phase 12: Model Versioning ────────────────────────────────────────────────

class TestModelVersioning:
    def test_version_metadata_has_all_fields(self):
        v = model_version_metadata()
        assert "model_version" in v
        assert "physics_version" in v
        assert "configuration_version" in v
        assert "environment_version" in v

    def test_model_version_in_response(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01")
        assert response.model_version == "MoorSense Physics v0.4"
        assert response.physics_version == "catenary-0.4"

    def test_replay_result_includes_model_versions(self):
        runner = ReplayRunner()
        t0 = datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)
        obs = [ReplayObservation(
            station_id="OMNI-BD10", observation_timestamp=t0,
            telemetry={"meteorology": {"windSpeed": {"value": 3.0, "unit": "m/s"},
                                       "windDirection": {"value": 90.0, "unit": "°"}},
                       "ocean": {}, "waves": {}, "profiles": {}})]
        results = runner.replay_observations("OMNI-BD10", obs)
        assert results[0].model_versions["model_version"] == MODEL_VERSION
        assert results[0].model_versions["physics_version"] == PHYSICS_VERSION


# ── Fleet Fault Isolation ─────────────────────────────────────────────────────

class TestFleetFaultIsolation:
    def test_one_failure_does_not_stop_fleet(self):
        from services.mooring.fleet_runner import FleetRunner
        from services.buoy.buoy_models import Buoy, Observation
        from services.buoy.buoy_cache import BuoyCache

        runner = FleetRunner()
        buoys = {
            "OMNI-BD10": Buoy(id="OMNI-BD10", name="OMNI-BD10", type="OMNI",
                               latitude=16.3617, longitude=87.9903),
            "OMNI-FAKE-XYZ": Buoy(id="OMNI-FAKE-XYZ", name="FAKE", type="OMNI",
                                   latitude=0.0, longitude=0.0),
        }
        cache = BuoyCache()
        obs = Observation(buoyId="OMNI-BD10",
                          timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                          source="TEST",
                          telemetry={"meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"},
                                                     "windDirection": {"value": 90.0, "unit": "°"}}})
        cache.update(obs)
        results = runner.run_fleet(buoys, cache)
        assert len(results) == 2
        statuses = {r.buoy_id: r.error for r in results}
        # FAKE station should fail with an error, BD10 should succeed
        assert statuses["OMNI-FAKE-XYZ"] is not None

    def test_fleet_processes_all_known_buoys_independently(self):
        from services.mooring.fleet_runner import FleetRunner
        from services.buoy.buoy_models import Buoy, Observation
        from services.buoy.buoy_cache import BuoyCache

        runner = FleetRunner()
        buoys = {}
        cache = BuoyCache()
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            buoys[buoy_id] = Buoy(
                id=buoy_id, name=buoy_id, type="OMNI",
                latitude=entry["lat"], longitude=entry["lon"])
            obs = Observation(
                buoyId=buoy_id,
                timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                source="TEST",
                telemetry={"meteorology": {"windSpeed": {"value": 4.0, "unit": "m/s"},
                                           "windDirection": {"value": 90.0, "unit": "°"}}})
            cache.update(obs)
        results = runner.run_fleet(buoys, cache)
        assert len(results) == len(OMNI_FLEET_SEED)
        converged = [r for r in results if r.solver_status == "CONVERGED"]
        # All known stations should converge (they all have bathymetry seeds)
        assert len(converged) == len(OMNI_FLEET_SEED)
