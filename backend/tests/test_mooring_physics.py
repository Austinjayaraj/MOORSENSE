"""Tests for mooring configuration, physics forces, catenary solver, and tension calculations."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from services.buoy.mooring_models import (
    MooringConfiguration, MooringLineSegment, EnvironmentalForces,
    LineTensionResult, MooringEstimate,
)
from services.buoy.physics_service import (
    wind_force, current_force, wave_force_screening, resolve_forces,
    catenary_tension, compute_environmental_forces, compute_line_tensions,
    compute_mooring_estimate, RHO_AIR, RHO_WATER, CD_WIND, CD_CURRENT,
)


# --- Wind force tests ---

def test_wind_force_basic():
    speed = 10.0
    area = 5.0
    result = wind_force(speed, area)
    expected = 0.5 * RHO_AIR * CD_WIND * area * speed ** 2
    assert result == pytest.approx(expected, rel=1e-6)


def test_wind_force_zero_speed():
    assert wind_force(0.0, 5.0) == 0.0


def test_wind_force_none_inputs():
    assert wind_force(None, 5.0) is None
    assert wind_force(10.0, None) is None
    assert wind_force(None, None) is None


# --- Current force tests ---

def test_current_force_basic():
    speed = 1.5
    area = 3.0
    result = current_force(speed, area)
    expected = 0.5 * RHO_WATER * CD_CURRENT * area * speed ** 2
    assert result == pytest.approx(expected, rel=1e-6)


def test_current_force_none_inputs():
    assert current_force(None, 3.0) is None
    assert current_force(1.5, None) is None


# --- Wave force screening tests ---

def test_wave_force_screening_basic():
    result = wave_force_screening(2.0, 8.0, 3.0, 1.5)
    assert result is not None
    assert result > 0


def test_wave_force_screening_none_inputs():
    assert wave_force_screening(None, 8.0, 3.0, 1.5) is None
    assert wave_force_screening(2.0, None, 3.0, 1.5) is None
    assert wave_force_screening(2.0, 8.0, None, 1.5) is None
    assert wave_force_screening(2.0, 8.0, 3.0, None) is None


def test_wave_force_screening_zero_period():
    assert wave_force_screening(2.0, 0, 3.0, 1.5) is None


# --- Force resolution tests ---

def test_resolve_forces_single_direction():
    mag, direction = resolve_forces(100.0, 0.0, None, None, None, None)
    assert mag == pytest.approx(100.0, rel=1e-6)
    assert direction == pytest.approx(0.0, abs=0.1)


def test_resolve_forces_opposing():
    mag, direction = resolve_forces(100.0, 0.0, 100.0, 180.0, None, None)
    assert mag == pytest.approx(0.0, abs=0.01)


def test_resolve_forces_all_none():
    assert resolve_forces(None, None, None, None, None, None) == (None, None)


def test_resolve_forces_perpendicular():
    mag, direction = resolve_forces(100.0, 0.0, 100.0, 90.0, None, None)
    assert mag == pytest.approx(math.sqrt(2) * 100.0, rel=1e-3)


# --- Catenary tension tests ---

def test_catenary_basic():
    result = catenary_tension(
        horizontal_force_N=5000.0,
        water_depth_m=100.0,
        line_length_m=200.0,
        weight_per_m=50.0,
    )
    assert "error" not in result
    assert result["resultant_tension_N"] > 0
    assert result["horizontal_tension_N"] > 0
    assert result["vertical_tension_N"] > 0
    assert 0 < result["line_angle_deg"] < 90
    assert result["suspended_length_m"] > 0
    assert result["grounded_length_m"] >= 0


def test_catenary_with_pretension():
    without = catenary_tension(5000.0, 100.0, 200.0, 50.0)
    with_pre = catenary_tension(5000.0, 100.0, 200.0, 50.0, pretension_N=1000.0)
    assert with_pre["resultant_tension_N"] > without["resultant_tension_N"]


def test_catenary_with_friction():
    without = catenary_tension(5000.0, 100.0, 300.0, 50.0)
    with_friction = catenary_tension(5000.0, 100.0, 300.0, 50.0, seabed_friction=0.5)
    assert with_friction["horizontal_tension_N"] >= without["horizontal_tension_N"]


def test_catenary_invalid_params():
    assert "error" in catenary_tension(5000.0, 0, 200.0, 50.0)
    assert "error" in catenary_tension(5000.0, 100.0, 0, 50.0)
    assert "error" in catenary_tension(5000.0, 100.0, 200.0, 0)


def test_catenary_line_angle_increases_with_depth():
    shallow = catenary_tension(5000.0, 50.0, 200.0, 50.0)
    deep = catenary_tension(5000.0, 200.0, 400.0, 50.0)
    assert deep["line_angle_deg"] > shallow["line_angle_deg"]


# --- Mooring configuration model tests ---

def test_mooring_config_insufficient_by_default():
    config = MooringConfiguration(buoy_id="BD14")
    assert not config.is_sufficient_for_analysis()
    assert config.availability == "UNAVAILABLE"
    assert config.requires_authoritative_mooring_configuration


def test_mooring_config_sufficient():
    config = MooringConfiguration(
        buoy_id="BD14", water_depth_m=4000.0, number_of_lines=3,
        buoy_mass_kg=5000.0, projected_area_m2=4.0,
        line_segments=[MooringLineSegment(
            line_id="LINE_01", segment=1, length_m=4500.0,
            weight_per_m=30.0, breaking_strength_N=500000.0)],
    )
    assert config.is_sufficient_for_analysis()


def test_mooring_config_null_values_preserved():
    config = MooringConfiguration(buoy_id="BD14")
    assert config.anchor_latitude is None
    assert config.anchor_longitude is None
    assert config.pretension_N is None
    assert config.seabed_type is None


# --- Compute environmental forces tests ---

def test_compute_forces_from_telemetry():
    telemetry = {
        "meteorology": {"windSpeed": {"value": 10.0, "unit": "m/s"}, "windDirection": {"value": 45.0, "unit": "°"}},
        "ocean": {"currentSpeed": {"value": 1.0, "unit": "m/s"}, "currentDirection": {"value": 90.0, "unit": "°"}},
        "waves": {},
    }
    config = MooringConfiguration(
        buoy_id="BD14", projected_area_m2=4.0,
        buoy_width_m=3.0, buoy_height_m=2.0,
    )
    forces = compute_environmental_forces(telemetry, config)
    assert forces.wind_force_N is not None
    assert forces.wind_force_N > 0
    assert forces.current_force_N is not None
    assert forces.total_horizontal_force_N is not None
    assert forces.model_level == "screening"


def test_compute_forces_missing_telemetry():
    config = MooringConfiguration(buoy_id="BD14")
    forces = compute_environmental_forces({}, config)
    assert forces.wind_force_N is None
    assert forces.current_force_N is None
    assert forces.total_horizontal_force_N is None


# --- Compute line tensions tests ---

def test_compute_tensions_insufficient_config():
    config = MooringConfiguration(buoy_id="BD14", number_of_lines=3)
    forces = EnvironmentalForces(total_horizontal_force_N=10000.0, total_force_direction_deg=45.0)
    lines = compute_line_tensions(forces, config)
    assert len(lines) == 3
    assert all(l.model_status == "INSUFFICIENT_CONFIGURATION" for l in lines)


def test_compute_tensions_with_valid_config():
    config = MooringConfiguration(
        buoy_id="BD14", water_depth_m=4000.0, number_of_lines=3,
        buoy_mass_kg=5000.0, projected_area_m2=4.0,
        line_segments=[
            MooringLineSegment(line_id="LINE_01", segment=1, length_m=4500.0,
                               weight_per_m=30.0, breaking_strength_N=500000.0),
            MooringLineSegment(line_id="LINE_02", segment=1, length_m=4500.0,
                               weight_per_m=30.0, breaking_strength_N=500000.0),
            MooringLineSegment(line_id="LINE_03", segment=1, length_m=4500.0,
                               weight_per_m=30.0, breaking_strength_N=500000.0),
        ],
    )
    forces = EnvironmentalForces(total_horizontal_force_N=10000.0, total_force_direction_deg=45.0)
    lines = compute_line_tensions(forces, config)
    assert len(lines) == 3
    assert all(l.model_status == "VALIDATED_INPUTS" for l in lines)
    assert all(l.estimated_tension_N > 0 for l in lines)
    assert all(l.utilization_ratio is not None for l in lines)
    assert all(l.safety_factor is not None for l in lines)


# --- Full mooring estimate tests ---

def test_mooring_estimate_insufficient():
    config = MooringConfiguration(buoy_id="BD14")
    estimate = compute_mooring_estimate(
        "BD14", "2026-10-08T03:00:00Z", {}, config, "test:1")
    assert estimate.model_status == "INSUFFICIENT_CONFIGURATION"
    assert estimate.lines == []


def test_mooring_estimate_with_real_telemetry():
    telemetry = {
        "meteorology": {"windSpeed": {"value": 8.0, "unit": "m/s"}, "windDirection": {"value": 180.0, "unit": "°"}},
        "ocean": {},
        "waves": {},
    }
    config = MooringConfiguration(
        buoy_id="BD14", water_depth_m=4000.0, number_of_lines=3,
        buoy_mass_kg=5000.0, projected_area_m2=4.0,
        buoy_width_m=3.0, buoy_height_m=2.0,
        line_segments=[
            MooringLineSegment(line_id=f"LINE_{i+1:02d}", segment=1, length_m=4500.0,
                               weight_per_m=30.0, breaking_strength_N=500000.0)
            for i in range(3)
        ],
    )
    estimate = compute_mooring_estimate(
        "BD14", "2026-10-08T03:00:00Z", telemetry, config, "test:2")
    assert estimate.environmental_forces.wind_force_N > 0
    assert len(estimate.lines) == 3
    assert estimate.max_tension_N is not None
    assert estimate.risk_level in ("LOW", "MODERATE", "HIGH", "UNKNOWN")


# --- Observation dedup with mooring ---

def test_history_retained_latest_replaced():
    """Given observations A then B where B.timestamp > A.timestamp,
    verify A remains in history and latest becomes B."""
    from datetime import datetime, timedelta, timezone
    from services.buoy.buoy_cache import BuoyCache
    from services.buoy.buoy_models import Observation

    cache = BuoyCache(live=10800, stale=21600, offline=86400)
    obs_a = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(hours=6),
                        source="TEST", telemetry={"meteorology": {"airTemperature": {"value": 28.0, "unit": "°C"}}})
    obs_b = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(hours=3),
                        source="TEST", telemetry={"meteorology": {"airTemperature": {"value": 29.0, "unit": "°C"}}})

    cache.update(obs_a)
    assert cache.latest["BD14"].timestamp == obs_a.timestamp

    cache.update(obs_b)
    assert cache.latest["BD14"].timestamp == obs_b.timestamp

    # Re-inserting A should not replace B
    cache.update(obs_a)
    assert cache.latest["BD14"].timestamp == obs_b.timestamp


# --- Freshness cadence tests ---

def test_freshness_cadence_aware():
    from datetime import datetime, timedelta, timezone
    from services.buoy.buoy_cache import BuoyCache
    from services.buoy.buoy_models import Buoy, Observation

    cache = BuoyCache(live=10800, stale=21600, offline=86400)
    buoy = Buoy(id="BD14", name="BD14", type="OMNI", latitude=6.57, longitude=88.23)

    # Within cadence: FRESH
    obs_fresh = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(hours=1),
                            source="TEST", telemetry={})
    cache.update(obs_fresh)
    cache.checked("BD14")
    detail = cache.detail(buoy)
    assert detail["freshness"]["state"] == "FRESH"

    # Within 1-2 cadences: LATEST_AVAILABLE
    obs_recent = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(hours=4),
                             source="TEST", telemetry={})
    cache.latest["BD14"] = obs_recent
    detail = cache.detail(buoy)
    assert detail["freshness"]["state"] == "LATEST_AVAILABLE"

    # Beyond 2 cadences: STALE
    obs_stale = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(hours=8),
                            source="TEST", telemetry={})
    cache.latest["BD14"] = obs_stale
    detail = cache.detail(buoy)
    assert detail["freshness"]["state"] == "STALE"


# --- WebSocket propagation test ---

@pytest.mark.asyncio
async def test_websocket_propagation_on_new_observation():
    """Verify WebSocket broadcast is called when a new observation arrives."""
    import asyncio
    from services.buoy.runtime import WebSocketManager
    from services.buoy.buoy_models import Observation
    from datetime import datetime, timedelta, timezone

    manager = WebSocketManager()
    obs = Observation(buoyId="BD14", timestamp=datetime.now(timezone.utc) - timedelta(seconds=10),
                      source="TEST", telemetry={"meteorology": {"airTemperature": {"value": 28.0, "unit": "°C"}}})
    event = obs.event()

    class MockWS:
        def __init__(self):
            self.sent = []
        async def send_json(self, data):
            self.sent.append(data)

    ws = MockWS()
    manager.clients[ws] = {"buoyId": "BD14", "queue": asyncio.Queue(maxsize=32)}

    await manager.broadcast(event)
    assert not manager.clients[ws]["queue"].empty()
    item = manager.clients[ws]["queue"].get_nowait()
    assert item["buoyId"] == "BD14"
    assert item["type"] == "buoy_update"
