"""Tests for station API endpoints returning real OMNI catalog."""
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.buoy.buoy_models import Buoy, Observation
from services.buoy.buoy_cache import BuoyCache
from services.buoy.runtime import BuoyRuntime, BuoySettings
from app.api.routes_stations import router as stations_router
from app.api.routes_buoys import router as buoys_router
from datetime import datetime, timedelta, timezone


CATALOG = [
    Buoy(id="OMNI-AD06", name="OMNI-AD06", type="OMNI", latitude=18.495, longitude=67.45),
    Buoy(id="OMNI-BD14", name="OMNI-BD14", type="OMNI", latitude=6.570556, longitude=88.233333),
    Buoy(id="OMNI-BD08", name="OMNI-BD08", type="OMNI", latitude=15.0, longitude=90.0),
]


class StubProvider:
    def __init__(self):
        self.observations = {}
        self.parameter_status = {}

    async def get_buoys(self):
        return CATALOG

    async def refresh(self):
        pass

    async def get_latest_observation(self, buoy_id):
        return None


def make_app(tmp_path):
    provider = StubProvider()
    rt = BuoyRuntime(provider, config=BuoySettings(
        buoy_outbox_path=str(tmp_path / "outbox.sqlite3"),
        buoy_ingestion_enabled=False))

    @asynccontextmanager
    async def lifespan(app):
        rt.buoys = {b.id: b for b in await rt.provider.get_buoys()}
        for buoy_id in rt.buoys:
            rt.cache.checked(buoy_id)
        app.state.buoy_runtime = rt
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(stations_router, prefix="/api")
    app.include_router(buoys_router)
    return app, rt


def test_stations_returns_omni_catalog(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/stations")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        ids = {s["id"] for s in data}
        assert "OMNI-AD06" in ids
        assert "OMNI-BD14" in ids


def test_stations_frontend_returns_omni_catalog(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/stations/frontend")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        for station in data:
            assert "latitude" in station
            assert "longitude" in station
            assert "data_status" in station


def test_station_by_id(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/stations/OMNI-BD14")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "OMNI-BD14"
        assert data["latitude"] == pytest.approx(6.570556)


def test_station_not_found(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/stations/NONEXISTENT")
        assert response.status_code == 404


def test_stations_with_observation_show_latest(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        ts = datetime.now(timezone.utc) - timedelta(hours=2)
        obs = Observation(buoyId="OMNI-BD14", timestamp=ts, source="TEST",
                          telemetry={"meteorology": {"airTemperature": {"value": 28.5, "unit": "°C"}}})
        rt.cache.update(obs)

        response = client.get("/api/stations")
        data = response.json()
        bd14 = next(s for s in data if s["id"] == "OMNI-BD14")
        assert bd14["latest_observation"] is not None
        assert bd14["data_status"] in ("FRESH", "LATEST_AVAILABLE", "STALE", "RECENT")


def test_telemetry_latest_endpoint(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        ts = datetime.now(timezone.utc) - timedelta(hours=1)
        obs = Observation(buoyId="OMNI-BD14", timestamp=ts, source="TEST",
                          telemetry={"meteorology": {"airTemperature": {"value": 28.5, "unit": "°C"},
                                                     "pressure": {"value": 1013.0, "unit": "hPa"}}})
        rt.cache.update(obs)

        response = client.get("/api/buoys/OMNI-BD14/telemetry/latest")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "LATEST_AVAILABLE"
        assert len(data["measurements"]) == 2
        params = {m["parameter"] for m in data["measurements"]}
        assert "airTemperature" in params
        assert "pressure" in params
        for m in data["measurements"]:
            assert m["availability"] == "measured"


def test_parameters_endpoint(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        ts = datetime.now(timezone.utc) - timedelta(hours=1)
        obs = Observation(buoyId="OMNI-BD14", timestamp=ts, source="TEST",
                          telemetry={"meteorology": {"airTemperature": {"value": 28.5, "unit": "°C"}},
                                     "waves": {"waveHeight": {"value": 2.1, "unit": "m"}}})
        rt.cache.update(obs)
        rt.provider.parameter_status["OMNI-BD14"] = {
            "air_temperature": "AVAILABLE", "wind_speed": "RESTRICTED",
            "hm0": "AVAILABLE", "current_speed": "NOT_OFFERED",
        }

        response = client.get("/api/buoys/OMNI-BD14/parameters")
        assert response.status_code == 200
        data = response.json()
        assert data["buoy_id"] == "OMNI-BD14"
        params = data["parameters"]
        assert params["air_temperature"]["status"] == "AVAILABLE"
        assert params["air_temperature"]["value"] == 28.5
        assert params["air_temperature"]["type"] == "measured"
        assert params["wind_speed"]["status"] == "RESTRICTED"
        assert params["wind_speed"]["value"] is None
        assert params["hm0"]["status"] == "AVAILABLE"
        assert params["hm0"]["value"] == 2.1
        assert params["current_speed"]["status"] == "NOT_OFFERED"
        assert params["current_speed"]["value"] is None


def test_mooring_endpoint_returns_unavailable(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/buoys/OMNI-BD14/mooring")
        assert response.status_code == 200
        data = response.json()
        assert data["availability"] == "UNAVAILABLE"
        assert data["requires_authoritative_mooring_configuration"] is True


def test_mooring_tension_insufficient(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/buoys/OMNI-BD14/mooring/tension")
        assert response.status_code == 200
        data = response.json()
        assert data["model_status"] == "INSUFFICIENT_CONFIGURATION"
        assert data["lines"] == []


def test_digital_twin_endpoint(tmp_path):
    app, rt = make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/buoys/OMNI-BD14/digital-twin")
        assert response.status_code == 200
        data = response.json()
        assert data["buoy_id"] == "OMNI-BD14"
        assert "telemetry" in data
        assert "mooring_configuration" in data
        assert "availability" in data
        assert data["availability"]["mooring_configuration"] == "UNAVAILABLE"
        assert "provenance" in data
        assert "limitations" in data
        assert isinstance(data["limitations"], list)
        assert data["derived"]["status"] == "INSUFFICIENT_CONFIGURATION"
