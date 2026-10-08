"""Tests for Phases 5B onwards: replay persistence schema, trajectory hardening,
validation framework, uncertainty refusal, sensitivity analysis, ML infrastructure,
anomaly engine, fleet health, and API endpoints.
"""
import sys
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest

# ── Phase 5B: Replay Migration ──────────────────────────────────────────────

def test_replay_migration_sql_exists():
    sql_path = Path(__file__).parents[1] / "migrations" / "005_mooring_replay.sql"
    assert sql_path.exists()
    content = sql_path.read_text()
    assert "mooring_replay_results" in content
    assert "UNIQUE" in content  # dedup key exists
    assert "ON CONFLICT" not in content  # handled in Python layer
    # Must have append-only note
    assert "Append-only" in content or "append-only" in content


def test_replay_migration_has_required_columns():
    sql = Path(__file__).parents[1].joinpath("migrations/005_mooring_replay.sql").read_text()
    required = [
        "station_id", "observation_timestamp",
        "model_version", "physics_version",
        "wind_speed", "current_speed", "wave_height",
        "estimated_tension_n", "data_risk", "model_risk", "mooring_risk",
        "confidence", "forcing_mode", "solver_status",
        "raw_result_json",
    ]
    for col in required:
        assert col in sql, f"Missing column: {col}"


def test_replay_migration_no_overwrite():
    """The UNIQUE constraint ensures idempotent replay, not destructive overwrite."""
    sql = Path(__file__).parents[1].joinpath("migrations/005_mooring_replay.sql").read_text()
    assert "UNIQUE" in sql
    # Must NOT have ON UPDATE or REPLACE
    assert "ON UPDATE" not in sql
    assert "REPLACE" not in sql


# ── Phase 7: Trajectory Hardening ───────────────────────────────────────────

from services.mooring.trajectory_service import (
    haversine_m, bearing_deg, analyze_trajectory, _trajectory_quality,
)


class TestHaversine:
    def test_zero_distance_identical_points(self):
        assert haversine_m(0, 0, 0, 0) == 0.0

    def test_one_degree_longitude_at_equator(self):
        d = haversine_m(0, 0, 0, 1)
        assert d == pytest.approx(111195, rel=0.01)

    def test_one_degree_latitude(self):
        d = haversine_m(0, 0, 1, 0)
        assert d == pytest.approx(111195, rel=0.01)

    def test_handles_longitude_near_180(self):
        d = haversine_m(0, 179.9, 0, -179.9)
        assert d > 0 and math.isfinite(d)

    def test_antipodal_points(self):
        d = haversine_m(0, 0, 0, 180)
        assert d == pytest.approx(math.pi * 6371000, rel=0.001)


class TestBearingDeg:
    def test_north(self):
        assert bearing_deg(0, 0, 1, 0) == pytest.approx(0, abs=0.1)

    def test_east(self):
        assert bearing_deg(0, 0, 0, 1) == pytest.approx(90, abs=0.5)

    def test_south(self):
        b = bearing_deg(1, 0, 0, 0)
        assert b == pytest.approx(180, abs=0.5)

    def test_identical_points(self):
        assert bearing_deg(0, 0, 0, 0) == 0.0


class TestTrajectoryQuality:
    def test_single_position_insufficient(self):
        q = _trajectory_quality([{"latitude": 15.0, "longitude": 90.0,
                                   "timestamp": "2026-01-01T00:00:00Z"}])
        assert q == "INSUFFICIENT"

    def test_two_positions_degraded(self):
        q = _trajectory_quality([
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"},
            {"latitude": 15.01, "longitude": 90.0, "timestamp": "2026-01-01T00:30:00Z"},
        ])
        assert q == "DEGRADED"  # < 2h span

    def test_good_trajectory(self):
        q = _trajectory_quality([
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"},
            {"latitude": 15.01, "longitude": 90.0, "timestamp": "2026-01-01T01:00:00Z"},
            {"latitude": 15.02, "longitude": 90.0, "timestamp": "2026-01-01T03:00:00Z"},
        ])
        assert q == "GOOD"


class TestAnalyzeTrajectory:
    def test_invalid_coordinates_filtered(self):
        positions = [
            {"latitude": 91.0, "longitude": 90.0},  # invalid lat
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"},
        ]
        result = analyze_trajectory("OMNI-BD10", positions)
        assert result.estimated_anchor_latitude == 15.0

    def test_empty_positions(self):
        result = analyze_trajectory("OMNI-BD10", [])
        assert result.estimated_anchor_latitude is None

    def test_single_position_low_confidence(self):
        result = analyze_trajectory("OMNI-BD10", [
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"}])
        assert result.provenance.confidence == "LOW"  # INSUFFICIENT quality

    def test_three_positions_good_confidence(self):
        result = analyze_trajectory("OMNI-BD10", [
            {"latitude": 15.00, "longitude": 90.00, "timestamp": "2026-01-01T00:00:00Z"},
            {"latitude": 15.01, "longitude": 90.01, "timestamp": "2026-01-01T01:30:00Z"},
            {"latitude": 15.02, "longitude": 90.02, "timestamp": "2026-01-01T03:00:00Z"},
        ])
        assert result.provenance.confidence == "MEDIUM"

    def test_anchor_never_called_actual(self):
        result = analyze_trajectory("OMNI-BD10", [
            {"latitude": 15.0, "longitude": 90.0, "timestamp": "2026-01-01T00:00:00Z"}])
        assert not hasattr(result, "actual_anchor_latitude")
        assert hasattr(result, "estimated_anchor_latitude")


# ── Phase 8: Validation Framework ───────────────────────────────────────────

from services.mooring.validation import (
    compare_model_measurement, VALIDATION_STATUS_NO_DATA, DISPLACEMENT_VALIDATION_STATUS,
    MeasuredTension, ValidationMetrics,
)


class TestValidationFramework:
    def test_no_measurements_returns_not_validated(self):
        result = compare_model_measurement([], [])
        assert result.validation_status == "NOT_VALIDATED"

    def test_mismatched_lengths_returns_not_validated(self):
        result = compare_model_measurement([1.0, 2.0], [1.0])
        assert result.validation_status == "NOT_VALIDATED"

    def test_valid_comparison_returns_metrics(self):
        modelled = [10.0, 12.0, 11.0]
        measured = [11.0, 12.5, 10.5]
        result = compare_model_measurement(modelled, measured)
        assert result.sample_count == 3
        assert result.mae is not None
        assert result.rmse is not None
        assert result.bias is not None

    def test_baseline_status_is_not_validated(self):
        assert VALIDATION_STATUS_NO_DATA.validation_status == "NOT_VALIDATED"
        assert "No physical measurements" in VALIDATION_STATUS_NO_DATA.notes

    def test_displacement_status_is_not_implemented(self):
        assert DISPLACEMENT_VALIDATION_STATUS.validation_status == "NOT_IMPLEMENTED"

    def test_measured_tension_not_fabricated_in_model(self):
        from services.mooring.models import MooringResponse
        response = MooringResponse(
            buoy_id="T", observation_timestamp="2026-01-01", model_timestamp="2026-01-01")
        assert response.measured_tension is None


# ── Phase 10: Uncertainty Framework ─────────────────────────────────────────

from services.mooring.uncertainty import (
    UncertaintySpec, run_monte_carlo, NOT_QUANTIFIED_RESULT,
)


class TestUncertainty:
    def test_no_specs_returns_not_quantified(self):
        result = run_monte_carlo([], lambda x: 1.0)
        assert result["output"].uncertainty_status == "NOT_QUANTIFIED"

    def test_monte_carlo_uniform(self):
        specs = [UncertaintySpec(
            parameter="depth", distribution="UNIFORM",
            lower=3000.0, upper=3500.0, source="TEST",
            provenance="SCENARIO_ASSUMPTION")]
        result = run_monte_carlo(specs, lambda x: x["depth"] * 1.22, n_samples=200, seed=42)
        assert result["output"].sample_count >= 10
        assert result["output"].p05 is not None
        assert result["output"].p50 is not None
        assert result["output"].p95 is not None
        assert result["output"].p05 < result["output"].p50 < result["output"].p95
        assert result["output"].uncertainty_status == "SCENARIO_ONLY"

    def test_monte_carlo_reproducible(self):
        specs = [UncertaintySpec(
            parameter="x", distribution="UNIFORM",
            lower=1.0, upper=2.0, source="TEST",
            provenance="SCENARIO_ASSUMPTION")]
        r1 = run_monte_carlo(specs, lambda x: x["x"] ** 2, seed=99)
        r2 = run_monte_carlo(specs, lambda x: x["x"] ** 2, seed=99)
        assert r1["output"].p50 == r2["output"].p50

    def test_not_quantified_is_default(self):
        assert NOT_QUANTIFIED_RESULT.uncertainty_status == "NOT_QUANTIFIED"


# ── Phase 10B: Sensitivity ───────────────────────────────────────────────────

from services.mooring.sensitivity import SensitivitySpec, run_sensitivity


class TestSensitivity:
    def test_scope_sensitivity(self):
        specs = [SensitivitySpec(
            parameter="scope", baseline=1.22, low=1.0, high=1.5,
            unit="", provenance="SCENARIO_ASSUMPTION")]
        baseline = {"scope": 1.22, "depth": 3000.0}

        def fn(params):
            return params["scope"] * params["depth"]

        results = run_sensitivity(specs, fn, baseline)
        assert len(results) == 1
        r = results[0]
        assert r.baseline_response == pytest.approx(3660.0, abs=1)
        assert r.low_response == pytest.approx(3000.0, abs=1)
        assert r.high_response == pytest.approx(4500.0, abs=1)
        assert r.response_range == pytest.approx(1500.0, abs=1)

    def test_no_specs_returns_empty(self):
        results = run_sensitivity([], lambda x: 1.0, {})
        assert results == []

    def test_provenance_preserved(self):
        specs = [SensitivitySpec(
            parameter="mbl", baseline=250000, low=200000, high=300000,
            unit="N", provenance="SCENARIO_ASSUMPTION",
            notes="Not a verified MBL")]
        results = run_sensitivity(specs, lambda x: x["mbl"] * 0.3, {"mbl": 250000})
        assert results[0].provenance == "SCENARIO_ASSUMPTION"


# ── Phase 13: ML Infrastructure ─────────────────────────────────────────────

from services.ml.dataset_builder import (
    SUPERVISED_TARGET_STATUS, MLDataset, DatasetRow,
)
from services.ml.splitter import chronological_split, station_holdout_split


class TestMLDataset:
    def test_supervised_target_unavailable(self):
        assert SUPERVISED_TARGET_STATUS == "UNAVAILABLE"

    def test_empty_dataset_no_target(self):
        ds = MLDataset()
        assert not ds.has_supervised_target()

    def test_dataset_without_physical_measurements(self):
        rows = [DatasetRow(
            station_id="OMNI-BD10",
            timestamp=datetime.now(timezone.utc),
            model_version="moorsense-0.4",
            configuration_version="omni-reference-1",
            wind_speed=5.0,
            measured_tension_n=None,
            validated=False)]
        ds = MLDataset(rows=rows)
        assert not ds.has_supervised_target()

    def test_feature_matrix_preserves_none(self):
        row = DatasetRow(
            station_id="OMNI-BD10",
            timestamp=datetime.now(timezone.utc),
            model_version="v1", configuration_version="v1",
            current_speed=None, wave_height=None)
        ds = MLDataset(rows=[row])
        features = ds.feature_matrix()
        assert features[0]["current_speed"] is None
        assert features[0]["wave_height"] is None


class TestTemporalSplit:
    def test_chronological_order_preserved(self):
        rows = [
            DatasetRow(station_id="T", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                       model_version="v1", configuration_version="v1"),
            DatasetRow(station_id="T", timestamp=datetime(2026, 6, 1, tzinfo=timezone.utc),
                       model_version="v1", configuration_version="v1"),
            DatasetRow(station_id="T", timestamp=datetime(2026, 12, 1, tzinfo=timezone.utc),
                       model_version="v1", configuration_version="v1"),
        ]
        ds = MLDataset(rows=rows)
        split = chronological_split(ds, train_frac=0.6, val_frac=0.2)
        # Train must be earlier than test
        if split.train and split.test:
            assert max(r.timestamp for r in split.train) < min(r.timestamp for r in split.test)

    def test_no_future_leakage(self):
        rows = [DatasetRow(
            station_id="T",
            timestamp=datetime(2026, 1, i + 1, tzinfo=timezone.utc),
            model_version="v1", configuration_version="v1")
            for i in range(10)]
        ds = MLDataset(rows=rows)
        split = chronological_split(ds)
        assert split.leakage_check_passed

    def test_station_holdout(self):
        rows = ([DatasetRow(station_id="OMNI-BD10",
                            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                            model_version="v1", configuration_version="v1")] * 3
                + [DatasetRow(station_id="OMNI-BD14",
                              timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                              model_version="v1", configuration_version="v1")] * 3)
        ds = MLDataset(rows=rows)
        train, test = station_holdout_split(ds, "OMNI-BD14")
        assert all(r.station_id == "OMNI-BD10" for r in train)
        assert all(r.station_id == "OMNI-BD14" for r in test)


# ── Phase 14: Anomaly Engine ─────────────────────────────────────────────────

from services.ml.anomaly_engine import assess_mooring_health


class TestAnomalyEngine:
    def test_wind_only_produces_watch_data_anomaly(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "WIND_ONLY", "LOW", "NORMAL", 0.2, 100.0, "CONVERGED")
        assert result.data_anomaly == "WATCH"

    def test_no_forcing_produces_insufficient(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "NO_FORCING", "UNKNOWN", "NORMAL", None, None, "NOT_RUN")
        assert result.data_anomaly == "INSUFFICIENT_DATA"

    def test_high_utilization_in_hypotheses(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "WIND_CURRENT_WAVE", "MEDIUM", "WARNING", 0.75, None, "CONVERGED")
        hypotheses = [h.hypothesis for h in result.hypotheses]
        assert "LINE_OVERLOAD" in hypotheses

    def test_failure_hypothesis_requires_validation(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "WIND_ONLY", "LOW", "CRITICAL", 0.85, None, "CONVERGED")
        for h in result.hypotheses:
            assert h.required_validation  # must specify what validation is needed

    def test_overall_is_worst_dimension(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "WIND_ONLY", "MEDIUM", "CRITICAL", 0.85, None, "CONVERGED")
        assert result.overall_health == "CRITICAL"

    def test_statistical_anomaly_not_called_failure(self):
        result = assess_mooring_health(
            "OMNI-BD10", "2026-10-08T03:00:00Z",
            "WIND_ONLY", "LOW", "WARNING", 0.65, None, "CONVERGED")
        # Status must be WATCH/WARNING/etc., not a string containing "FAILURE"
        assert "FAILURE" not in result.overall_health
        assert "FAILURE" not in result.engineering_risk


# ── Phase 11: Physics / Solver Hardening ────────────────────────────────────

from services.mooring.catenary_solver import solve_catenary
from services.mooring.models import MooringConfiguration, MooringLineSegment, ProvenancedValue, DataProvenance


def _basic_config(depth: float = 3000.0, line_length: float = 3660.0,
                   weight: float = 5.0, mbl: float = 250000.0) -> MooringConfiguration:
    return MooringConfiguration(
        buoy_id="TEST",
        water_depth=ProvenancedValue(value=depth, unit="m",
            provenance=DataProvenance(source="TEST", status="INFERRED", confidence="HIGH")),
        total_line_length=ProvenancedValue(value=line_length, unit="m",
            provenance=DataProvenance(source="TEST", status="DERIVED", confidence="MEDIUM")),
        segments=[MooringLineSegment(
            name="main", length_m=line_length, submerged_weight_n_m=weight,
            breaking_strength_n=mbl)])


class TestSolverHardening:
    def test_zero_force_converges(self):
        sol = solve_catenary(_basic_config(), 0.0)
        assert sol.converged
        assert sol.fairlead_tension_n > 0

    def test_negative_depth_no_converge(self):
        config = MooringConfiguration(
            buoy_id="T",
            water_depth=ProvenancedValue(value=-100, unit="m",
                provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3000, unit="m",
                provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="m", length_m=3000, submerged_weight_n_m=5)])
        sol = solve_catenary(config, 5000.0)
        assert not sol.converged

    def test_very_short_line_less_than_depth(self):
        sol = solve_catenary(_basic_config(depth=3000, line_length=500), 5000.0)
        assert sol.suspended_length_m <= 500.0

    def test_residual_is_finite(self):
        sol = solve_catenary(_basic_config(), 5000.0)
        assert math.isfinite(sol.residual)

    def test_tension_increases_monotonically(self):
        forces = [0.0, 1000.0, 5000.0, 10000.0, 50000.0]
        tensions = []
        for f in forces:
            sol = solve_catenary(_basic_config(), f)
            if sol.converged:
                tensions.append(sol.fairlead_tension_n)
        for i in range(1, len(tensions)):
            assert tensions[i] >= tensions[i - 1]

    def test_utilization_decreases_when_mbl_doubles(self):
        from services.mooring.catenary_solver import compute_utilization
        config1 = _basic_config(mbl=250000)
        config2 = _basic_config(mbl=500000)
        sol = solve_catenary(config1, 5000.0)
        u1 = compute_utilization(sol.fairlead_tension_n, config1.segments)
        u2 = compute_utilization(sol.fairlead_tension_n, config2.segments)
        assert u1 is not None and u2 is not None
        assert u1 == pytest.approx(u2 * 2, rel=0.01)  # double MBL = half utilization

    def test_no_mbl_returns_none_utilization(self):
        from services.mooring.catenary_solver import compute_utilization
        config = MooringConfiguration(
            buoy_id="T",
            water_depth=ProvenancedValue(value=3000, unit="m",
                provenance=DataProvenance(source="T", status="INFERRED", confidence="HIGH")),
            total_line_length=ProvenancedValue(value=3660, unit="m",
                provenance=DataProvenance(source="T", status="DERIVED", confidence="MEDIUM")),
            segments=[MooringLineSegment(name="m", length_m=3660, submerged_weight_n_m=5)])
        sol = solve_catenary(config, 5000.0)
        assert compute_utilization(sol.fairlead_tension_n, config.segments) is None
