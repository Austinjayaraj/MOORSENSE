"""Regression tests for BD10 telemetry data-correctness bugs.

These tests reproduce the exact conditions observed in the verified BD10
source data at 2026-10-08T03:00:00Z and verify all critical fixes.
"""
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
from services.buoy.telemetry_normalizer import (
    combine_series, _resolve_unit, CANONICAL_PARAM_UNITS,
    MET_FIELDS, WAVE_FIELDS, CURRENT_FIELDS, OCEAN_FIELDS,
)
from app.api.routes_buoys import router as buoys_router

BD10 = Buoy(id='OMNI-BD10', name='OMNI-BD10', type='OMNI', latitude=15.0, longitude=90.0)
EPOCH = 1791428400000  # 2026-10-08T03:00:00Z


def build_bd10_series():
    """Reproduce the exact BD10 series that triggers the bugs.

    Key issue: INCOIS returns incorrect y-axis units for some parameters.
    water_temperature charts may report "cm/s" as the unit.
    salinity charts may report "Deg C" as the unit.
    The normalizer must use canonical units regardless.
    """
    return {
        'air_temperature': ([(EPOCH, 30.704)], 'Deg C', 'https://incois'),
        'air_pressure': ([(EPOCH, 1016.08)], 'hPa', 'https://incois'),
        'humidity': ([(EPOCH, 73.248)], '%', 'https://incois'),
        'wind_speed': ([(EPOCH, 0.03)], 'm/s', 'https://incois'),
        'wind_direction': ([(EPOCH, 43.205)], 'Deg', 'https://incois'),
        'wind_gust': ([(EPOCH, 1.173)], 'm/s', 'https://incois'),
        'irradiance': ([(EPOCH, 326.768)], 'W/m2', 'https://incois'),
        # Temperature profile: INCOIS chart y-axis says "cm/s" (BUG)
        'water_temperature_1m': ([(EPOCH, 30.47)], 'cm/s', 'https://incois'),
        'water_temperature_10m': ([(EPOCH, 30.0)], 'cm/s', 'https://incois'),
        'water_temperature_500m': ([(EPOCH, 8.5)], 'cm/s', 'https://incois'),
        # Salinity profile: INCOIS chart y-axis says "Deg C" (BUG)
        'salinity_1m': ([(EPOCH, 31.3534457412)], 'Deg C', 'https://incois'),
        'salinity_500m': ([(EPOCH, 34.9)], 'psupsu', 'https://incois'),
    }


class TestCanonicalUnits:
    """BUG 4: Parameter-specific canonical unit preservation."""

    def test_temperature_canonical_unit(self):
        assert _resolve_unit('air_temperature', 'Deg C') == '°C'

    def test_pressure_canonical_unit(self):
        assert _resolve_unit('air_pressure', 'hPa') == 'hPa'

    def test_humidity_canonical_unit(self):
        assert _resolve_unit('humidity', '%') == '%'

    def test_wind_speed_canonical_unit(self):
        assert _resolve_unit('wind_speed', 'm/s') == 'm/s'

    def test_wind_direction_canonical_unit(self):
        assert _resolve_unit('wind_direction', 'Deg') == '°'

    def test_irradiance_canonical_unit(self):
        assert _resolve_unit('irradiance', 'W/m2') == 'W/m²'

    def test_sst_canonical_unit(self):
        assert _resolve_unit('sst', 'anything') == '°C'

    def test_surface_salinity_canonical_unit(self):
        assert _resolve_unit('surface_salinity', 'anything') == 'PSU'

    def test_hm0_canonical_unit(self):
        assert _resolve_unit('hm0', 'anything') == 'm'

    def test_current_speed_canonical_unit(self):
        assert _resolve_unit('current_speed', 'anything') == 'm/s'

    def test_temperature_profile_canonical_overrides_bogus_source(self):
        """BUG 3: water_temperature_1m with source unit 'cm/s' must become °C."""
        assert _resolve_unit('water_temperature_1m', 'cm/s') == '°C'

    def test_salinity_profile_canonical_overrides_bogus_source(self):
        """BUG 3: salinity_1m with source unit 'Deg C' must become PSU."""
        assert _resolve_unit('salinity_1m', 'Deg C') == 'PSU'

    def test_salinity_profile_canonical_overrides_psupsu(self):
        """salinity_500m with source unit 'psupsu' must become PSU."""
        assert _resolve_unit('salinity_500m', 'psupsu') == 'PSU'

    def test_current_profile_speed_canonical(self):
        assert _resolve_unit('current_speed_50m', 'm/s') == 'm/s'

    def test_current_profile_direction_canonical(self):
        assert _resolve_unit('current_direction_50m', 'Deg') == '°'


class TestCombineSeriesUnits:
    """BUGs 1-3: Verify combine_series produces correct units from BD10 data."""

    def _obs(self):
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        assert len(rows) == 1
        return rows[0]

    def test_sst_value_and_unit(self):
        """BUG 1: SST must be 30.47 °C, not cm/s."""
        obs = self._obs()
        assert obs.telemetry.ocean['sst'].value == 30.47
        assert obs.telemetry.ocean['sst'].unit == '°C'

    def test_surface_salinity_value_and_unit(self):
        """BUG 2: Surface salinity must be PSU, not °C."""
        obs = self._obs()
        assert obs.telemetry.ocean['salinity'].value == 31.3534457412
        assert obs.telemetry.ocean['salinity'].unit == 'PSU'

    def test_1m_temperature_profile_unit(self):
        """BUG 3: 1m temperature profile must be °C."""
        obs = self._obs()
        temp_profile = obs.telemetry.profiles['temperature']
        p1m = next(p for p in temp_profile if p.depth == 1)
        assert p1m.value == 30.47
        assert p1m.unit == '°C'

    def test_1m_salinity_profile_unit(self):
        """BUG 3: 1m salinity profile must be PSU."""
        obs = self._obs()
        sal_profile = obs.telemetry.profiles['salinity']
        p1m = next(p for p in sal_profile if p.depth == 1)
        assert p1m.value == 31.3534457412
        assert p1m.unit == 'PSU'

    def test_500m_salinity_unit_normalized(self):
        """BUG 3: 500m salinity with source 'psupsu' must normalize to PSU."""
        obs = self._obs()
        sal_profile = obs.telemetry.profiles['salinity']
        p500m = next(p for p in sal_profile if p.depth == 500)
        assert p500m.value == 34.9
        assert p500m.unit == 'PSU'

    def test_source_epoch_preserved_in_raw_payload(self):
        """BUG 5: source_epoch_ms must be in rawPayload."""
        obs = self._obs()
        assert obs.rawPayload['sourceEpochMs'] == EPOCH

    def test_meteorology_units_correct(self):
        obs = self._obs()
        met = obs.telemetry.meteorology
        assert met['airTemperature'].unit == '°C'
        assert met['pressure'].unit == 'hPa'
        assert met['humidity'].unit == '%'
        assert met['windSpeed'].unit == 'm/s'
        assert met['windDirection'].unit == '°'
        assert met['windGust'].unit == 'm/s'
        assert met['radiation'].unit == 'W/m²'

    def test_utc_timestamp_preserved(self):
        """BUG 9: Observation timestamp must be 2026-10-08T03:00:00Z."""
        obs = self._obs()
        assert obs.timestamp == datetime(2026, 10, 8, 3, 0, 0, tzinfo=timezone.utc)


class TestParametersAPI:
    """BUGs 1-2, 6-7: /parameters endpoint correctness."""

    @staticmethod
    def _make_app(tmp_path):
        class StubProvider:
            parameter_status = {}
            async def get_buoys(self): return [BD10]
            async def refresh(self): pass
            async def get_latest_observation(self, _): return None

        rt = BuoyRuntime(StubProvider(), config=BuoySettings(
            buoy_outbox_path=str(tmp_path / 'outbox.sqlite3'),
            buoy_ingestion_enabled=False))

        @asynccontextmanager
        async def lifespan(app):
            rt.buoys = {BD10.id: BD10}
            rt.cache.checked(BD10.id)
            app.state.buoy_runtime = rt
            yield

        app = FastAPI(lifespan=lifespan)
        app.include_router(buoys_router)
        return app, rt

    def test_sst_status_available_with_profile_promotion(self, tmp_path):
        """BUG 1: SST promoted from water_temperature_1m must show AVAILABLE."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        rt.provider.parameter_status[BD10.id] = {
            'air_temperature': 'AVAILABLE', 'sst': 'NOT_OFFERED',
        }
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/parameters').json()
            sst = data['parameters']['sst']
            assert sst['status'] == 'AVAILABLE'
            assert sst['value'] == 30.47
            assert sst['unit'] == '°C'
            assert sst['type'] == 'measured'

    def test_surface_salinity_status_available_with_profile_promotion(self, tmp_path):
        """BUG 2: surface_salinity promoted from salinity_1m must show AVAILABLE."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        rt.provider.parameter_status[BD10.id] = {
            'surface_salinity': 'NOT_OFFERED',
        }
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/parameters').json()
            sal = data['parameters']['surface_salinity']
            assert sal['status'] == 'AVAILABLE'
            assert sal['value'] == 31.3534457412
            assert sal['unit'] == 'PSU'
            assert sal['type'] == 'measured'

    def test_impossible_state_not_offered_with_value(self, tmp_path):
        """BUG 6: NOT_OFFERED + non-null value must not occur."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        rt.provider.parameter_status[BD10.id] = {}
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/parameters').json()
            for key, param in data['parameters'].items():
                if param['status'] in ('NOT_OFFERED', 'RESTRICTED', 'SOURCE_UNAVAILABLE'):
                    assert param['value'] is None, \
                        f"{key}: status={param['status']} but value={param['value']}"

    def test_measured_type_on_available_values(self, tmp_path):
        """BUG 7: AVAILABLE values with non-null must have type=measured."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        rt.provider.parameter_status[BD10.id] = {
            'air_temperature': 'AVAILABLE', 'wind_speed': 'AVAILABLE',
        }
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/parameters').json()
            at = data['parameters']['air_temperature']
            assert at['type'] == 'measured'
            assert at['source'] == 'INCOIS'

    def test_source_epoch_in_telemetry_latest(self, tmp_path):
        """BUG 5: source_epoch_ms must be present in telemetry/latest."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/telemetry/latest').json()
            assert data['source_epoch_ms'] == EPOCH
            for m in data['measurements']:
                assert m['source_epoch_ms'] == EPOCH

    def test_telemetry_latest_units(self, tmp_path):
        """Verify all telemetry/latest units are canonical, not chart y-axis."""
        app, rt = self._make_app(tmp_path)
        series = build_bd10_series()
        rows = combine_series(BD10.id, series, BD10)
        rt.cache.update(rows[0])
        with TestClient(app) as client:
            data = client.get(f'/api/buoys/{BD10.id}/telemetry/latest').json()
            by_param = {m['parameter']: m for m in data['measurements']}
            assert by_param['sst']['unit'] == '°C'
            assert by_param['salinity']['unit'] == 'PSU'
            assert by_param['airTemperature']['unit'] == '°C'
            assert by_param['pressure']['unit'] == 'hPa'
            # Profile temperatures must be °C, not cm/s
            temp_profiles = [m for m in data['measurements']
                            if m['parameter'] == 'temperature' and m.get('depth_m') is not None]
            for p in temp_profiles:
                assert p['unit'] == '°C', f"depth {p['depth_m']}: unit={p['unit']}"
            # Profile salinities must be PSU
            sal_profiles = [m for m in data['measurements']
                           if m['parameter'] == 'salinity' and m.get('depth_m') is not None]
            for p in sal_profiles:
                assert p['unit'] == 'PSU', f"depth {p['depth_m']}: unit={p['unit']}"
