"""Phase 3 provenance audit tests.

Verifies that authoritative config overrides reference, ASSUMPTION provenance is
properly propagated, confidence degrades correctly, missing environmental data
remains UNKNOWN/null, and the measured-tension hook works without fabrication.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest

from services.mooring.models import (
    MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance,
    EnvironmentalState, MooringResponse, MeasuredTensionHook, ConfidenceBreakdown,
)
from services.mooring.config_resolver import (
    MooringConfigResolver, OMNI_SCOPE, _assumption_prov, _ref_prov,
)
from services.mooring.bathymetry_service import BathymetryService
from services.mooring.confidence import compute_confidence
from services.mooring.mooring_response import compute_mooring_response, extract_environmental_state
from services.mooring.catenary_solver import compute_utilization, compute_safety_factor


# ── Provenance Status Tests ───────────────────────────────────────────────────

class TestProvenanceStatus:
    def test_assumption_status_exists_in_literal(self):
        """ASSUMPTION must be a valid ProvenanceStatus."""
        from services.mooring.models import ProvenanceStatus
        # Construct a DataProvenance with ASSUMPTION — must not raise
        pv = DataProvenance(source="test", status="ASSUMPTION", confidence="LOW")
        assert pv.status == "ASSUMPTION"

    def test_line_segments_use_assumption_not_reference(self):
        """After Phase 3, reference segments must use ASSUMPTION not REFERENCE provenance."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        for seg in config.segments:
            assert seg.provenance.status == "ASSUMPTION", \
                f"Segment '{seg.name}' has status={seg.provenance.status}, expected ASSUMPTION"

    def test_pretension_uses_assumption_provenance(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.pretension_n is not None
        assert config.pretension_n.provenance.status == "ASSUMPTION"
        assert config.pretension_n.provenance.confidence == "LOW"

    def test_fairlead_depth_uses_assumption_provenance(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.fairlead_depth_m is not None
        assert config.fairlead_depth_m.provenance.status == "ASSUMPTION"

    def test_scope_uses_reference_provenance(self):
        """Scope 1.22 is from published NIOT/INCOIS design — REFERENCE, not ASSUMPTION."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.scope.provenance.status == "REFERENCE"

    def test_water_depth_uses_inferred_provenance(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.water_depth.provenance.status == "INFERRED"

    def test_line_length_uses_derived_provenance(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        assert config.total_line_length.provenance.status == "DERIVED"


# ── Authoritative Override Tests ──────────────────────────────────────────────

class TestAuthoritativeOverride:
    def test_authoritative_config_overrides_reference(self):
        resolver = MooringConfigResolver()
        authoritative_data = {
            "water_depth_m": 2700, "source": "NIOT_DEPLOYMENT", "scope": 1.22,
            "total_line_length_m": 3294, "line_count": 1,
            "segments": [{
                "name": "main_line", "length_m": 3294,
                "submerged_weight_n_m": 6.5, "breaking_strength_n": 350000,
            }]
        }
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903, authoritative=authoritative_data)
        assert config.configuration_status == "AUTHORITATIVE"
        assert config.water_depth.value == 2700
        assert config.water_depth.provenance.status == "AUTHORITATIVE"
        assert config.water_depth.provenance.confidence == "HIGH"
        # Segments from authoritative data are also AUTHORITATIVE
        assert config.segments[0].provenance.status == "AUTHORITATIVE"

    def test_station_specific_overrides_fleet_default(self):
        """Each station gets independent resolution — not shared state."""
        resolver = MooringConfigResolver()
        c1 = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        c2 = resolver.resolve("OMNI-BD14", 6.5706, 88.2333)
        # Different depths → different line lengths
        assert c1.water_depth.value != c2.water_depth.value
        assert c1.total_line_length.value != c2.total_line_length.value

    def test_missing_mbl_prevents_utilization(self):
        """If MBL is not available, utilization must be null."""
        config = MooringConfiguration(
            buoy_id="T",
            water_depth=ProvenancedValue(value=3000, unit="m",
                provenance=DataProvenance(source="TEST", status="INFERRED", confidence="MEDIUM")),
            total_line_length=ProvenancedValue(value=3660, unit="m",
                provenance=DataProvenance(source="TEST", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="m", length_m=3660, submerged_weight_n_m=5.0)])
        # breaking_strength_n is None — utilization must be null
        util = compute_utilization(15000.0, config.segments)
        assert util is None

    def test_missing_mbl_prevents_safety_factor(self):
        config = MooringConfiguration(
            buoy_id="T",
            segments=[MooringLineSegment(name="m", length_m=3000, submerged_weight_n_m=5.0)])
        sf = compute_safety_factor(15000.0, config.segments)
        assert sf is None


# ── Environmental Missing-Data Tests ─────────────────────────────────────────

class TestEnvironmentalMissingData:
    def test_missing_current_not_zero(self):
        env = extract_environmental_state({
            "meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"}},
            "ocean": {}, "waves": {}, "profiles": {},
        })
        assert env.current_speed_ms is None
        assert env.sources.get("current") == "UNAVAILABLE"

    def test_missing_wave_not_zero(self):
        env = extract_environmental_state({
            "meteorology": {}, "ocean": {}, "waves": {}, "profiles": {},
        })
        assert env.wave_height_m is None
        assert env.sources.get("wave") == "UNAVAILABLE"

    def test_wind_only_mode_labeled(self):
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
        assert response.forcing_mode == "WIND_ONLY"
        assert response.environmental_completeness == "PARTIAL_WIND_ONLY"

    def test_full_forcing_mode_labeled(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        telemetry = {
            "meteorology": {"windSpeed": {"value": 8.0, "unit": "m/s"},
                            "windDirection": {"value": 90.0, "unit": "°"}},
            "ocean": {"currentSpeed": {"value": 0.5, "unit": "m/s"},
                      "currentDirection": {"value": 90.0, "unit": "°"}},
            "waves": {"waveHeight": {"value": 2.0, "unit": "m"},
                      "wavePeriod": {"value": 8.0, "unit": "s"},
                      "waveDirection": {"value": 90.0, "unit": "°"}},
            "profiles": {},
        }
        response = compute_mooring_response(
            "OMNI-BD10", 16.3617, 87.9903, telemetry,
            "2026-10-08T03:00:00Z", resolver, telemetry_age_seconds=3600)
        assert response.forcing_mode == "WIND_CURRENT_WAVE"
        assert response.environmental_completeness == "FULL"


# ── Confidence Degradation Tests ──────────────────────────────────────────────

class TestConfidenceDegradation:
    def test_assumption_line_properties_cap_at_low(self):
        """ASSUMPTION material properties must prevent MEDIUM/HIGH confidence."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        # Reference config uses ASSUMPTION for line segments
        env = EnvironmentalState(wind_speed_ms=10, current_speed_ms=0.5, wave_height_m=2.0)
        overall, breakdown = compute_confidence(config, env, "CONVERGED", 3600)
        assert overall == "LOW", f"Expected LOW confidence with ASSUMPTION materials, got {overall}"
        assert breakdown.material_properties == "LOW"

    def test_wind_only_confidence_is_low(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        env = EnvironmentalState(wind_speed_ms=5.0)  # wind only
        overall, breakdown = compute_confidence(config, env, "CONVERGED", 3600)
        assert overall == "LOW"
        assert breakdown.environmental_data == "LOW"

    def test_missing_telemetry_confidence_unknown(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        env = EnvironmentalState()
        overall, breakdown = compute_confidence(config, env, "NOT_RUN", None)
        assert breakdown.telemetry == "UNKNOWN"
        assert overall in ("LOW", "UNKNOWN")

    def test_inferred_depth_not_high_bathymetry(self):
        """GEBCO depth is INFERRED → bathymetry confidence must be at most MEDIUM."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        env = EnvironmentalState(wind_speed_ms=5.0)
        _, breakdown = compute_confidence(config, env, "CONVERGED", 3600)
        assert breakdown.bathymetry in ("MEDIUM", "LOW"), \
            f"GEBCO inferred depth should be MEDIUM or LOW confidence, got {breakdown.bathymetry}"

    def test_confidence_breakdown_has_all_dimensions(self):
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        env = EnvironmentalState(wind_speed_ms=5.0)
        overall, breakdown = compute_confidence(config, env, "CONVERGED", 3600)
        assert isinstance(breakdown, ConfidenceBreakdown)
        assert breakdown.telemetry is not None
        assert breakdown.bathymetry is not None
        assert breakdown.configuration is not None
        assert breakdown.environmental_data is not None
        assert breakdown.material_properties is not None
        assert breakdown.physics_convergence is not None
        assert breakdown.overall == overall


# ── Measured Tension Hook Tests ───────────────────────────────────────────────

class TestMeasuredTensionHook:
    def test_measured_tension_is_none_by_default(self):
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01")
        assert response.measured_tension is None

    def test_measured_tension_can_be_set(self):
        hook = MeasuredTensionHook(
            measured_tension_n=15000.0,
            sensor_id="BD10-TENSION-01",
            observation_timestamp="2026-10-08T03:00:00Z")
        response = MooringResponse(
            buoy_id="BD10", observation_timestamp="2026-01-01", model_timestamp="2026-01-01",
            fairlead_tension_n=14500.0, measured_tension=hook)
        assert response.measured_tension.measured_tension_n == 15000.0
        assert response.measured_tension.source == "PHYSICAL_SENSOR"

    def test_model_error_can_be_computed(self):
        """Model vs measured comparison is only meaningful with real data."""
        model_t = 14500.0
        measured_t = 15000.0
        error = measured_t - model_t
        rel_error = abs(error) / measured_t
        hook = MeasuredTensionHook(
            measured_tension_n=measured_t,
            model_error_n=error,
            model_relative_error=rel_error)
        assert hook.model_error_n == 500.0
        assert hook.model_relative_error == pytest.approx(1/30, rel=1e-4)

    def test_measured_tension_not_fabricated_in_pipeline(self):
        """The pipeline must not inject a measured tension value."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        telemetry = {"meteorology": {"windSpeed": {"value": 5.0, "unit": "m/s"},
                                     "windDirection": {"value": 0.0, "unit": "°"}},
                     "ocean": {}, "waves": {}, "profiles": {}}
        response = compute_mooring_response(
            "OMNI-BD10", 16.3617, 87.9903, telemetry,
            "2026-10-08T03:00:00Z", resolver, telemetry_age_seconds=3600)
        assert response.measured_tension is None


# ── Trajectory Estimated-Anchor Tests ────────────────────────────────────────

class TestTrajectoryEstimate:
    def test_anchor_from_single_position_is_estimated(self):
        from services.mooring.trajectory_service import analyze_trajectory
        positions = [{"latitude": 16.36, "longitude": 87.99, "timestamp": "2026-01-01T00:00:00Z"}]
        result = analyze_trajectory("OMNI-BD10", positions)
        assert result.provenance.status == "ESTIMATED"
        # Single position → quality=INSUFFICIENT → LOW confidence (more accurate)
        assert result.provenance.confidence in ("LOW", "MEDIUM")

    def test_anchor_from_authoritative_source_is_not_estimated(self):
        from services.mooring.trajectory_service import analyze_trajectory
        positions = [{"latitude": 16.36, "longitude": 87.99, "timestamp": "2026-01-01T00:00:00Z"}]
        result = analyze_trajectory("OMNI-BD10", positions,
                                    anchor_lat=16.0, anchor_lon=87.5)
        assert result.provenance.status == "AUTHORITATIVE"

    def test_estimated_anchor_not_called_actual(self):
        from services.mooring.trajectory_service import analyze_trajectory
        positions = [{"latitude": 16.36, "longitude": 87.99, "timestamp": "2026-01-01T00:00:00Z"}]
        result = analyze_trajectory("OMNI-BD10", positions)
        # The model has 'estimated_anchor_latitude' — must not have 'actual_anchor'
        assert not hasattr(result, "actual_anchor_latitude")
        assert hasattr(result, "estimated_anchor_latitude")


# ── No Fabrication Tests ──────────────────────────────────────────────────────

class TestNoFabrication:
    def test_no_fake_mooring_measurements(self):
        """The system must never mark mooring engineering values as MEASURED."""
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        config = resolver.resolve("OMNI-BD10", 16.3617, 87.9903)
        measured_statuses = {"MEASURED"}
        for seg in config.segments:
            assert seg.provenance.status not in measured_statuses, \
                f"Segment '{seg.name}' falsely marked as MEASURED"
        if config.pretension_n:
            assert config.pretension_n.provenance.status not in measured_statuses

    def test_response_tension_not_measured(self):
        """Solver output tension is DERIVED/MODELLED, not MEASURED."""
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01",
            fairlead_tension_n=15000.0, solver_status="CONVERGED")
        # No 'type=MEASURED' on tension — the response carries no such field
        # Absence of measured_tension field confirms it's not falsely labeled
        assert response.measured_tension is None
        assert response.fairlead_tension_n == 15000.0

    def test_all_fleet_buoys_maintain_assumption_provenance(self):
        from services.mooring.bathymetry_service import OMNI_FLEET_SEED
        svc = BathymetryService()
        resolver = MooringConfigResolver(svc)
        for buoy_id, entry in OMNI_FLEET_SEED.items():
            config = resolver.resolve(buoy_id, entry["lat"], entry["lon"])
            assert config.configuration_status == "REFERENCE"
            assert config.water_depth.provenance.status == "INFERRED"
            assert config.total_line_length.provenance.status == "DERIVED"
            for seg in config.segments:
                assert seg.provenance.status == "ASSUMPTION"
