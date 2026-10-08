"""Tests for expanded OMNI parameter discovery, normalization, and availability tracking."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
import pytest
import httpx

from services.buoy.buoy_models import Buoy, Observation
from services.buoy.telemetry_normalizer import (
    parse_chart, combine_series,
    MET_FIELDS, WAVE_FIELDS, CURRENT_FIELDS, OCEAN_FIELDS,
)
from services.buoy.incois_provider import (
    IncoisBuoyProvider, CORE_PARAMETERS, KNOWN_PARAMETERS,
)

STATION = Buoy(id='OMNI-BD14', name='BD14', type='OMNI', latitude=6.57, longitude=88.23)
EPOCH = 1791428400000  # 2026-10-08T03:00:00Z


def make_chart_html(parameter_name, value, unit_str, options=None):
    """Build a minimal chart HTML fixture with the given data."""
    opts = options or [parameter_name, 'air_temperature']
    select = ''.join(f'<option value="{o}">{o}</option>' for o in opts)
    return (f'<select id="parameter">{select}</select>'
            f"yAxis: [{{title: {{text: [\"{unit_str}\"]}}}}],"
            f" series: [{{name: 'MB Data', data: [[{EPOCH},{value}]]}}]")


# ──────────────────────────────────────────────────────────
# Normalizer mapping coverage
# ──────────────────────────────────────────────────────────

class TestMeteorologyMappings:
    def test_air_temperature(self):
        assert MET_FIELDS['air_temperature'] == 'airTemperature'

    def test_air_pressure(self):
        assert MET_FIELDS['air_pressure'] == 'pressure'

    def test_humidity(self):
        assert MET_FIELDS['humidity'] == 'humidity'

    def test_rainfall(self):
        assert MET_FIELDS['rainfall'] == 'rainfall'

    def test_wind_speed(self):
        assert MET_FIELDS['wind_speed'] == 'windSpeed'

    def test_wind_direction(self):
        assert MET_FIELDS['wind_direction'] == 'windDirection'

    def test_wind_gust(self):
        assert MET_FIELDS['wind_gust'] == 'windGust'

    def test_irradiance(self):
        assert MET_FIELDS['irradiance'] == 'radiation'

    def test_shortwave_radiation(self):
        assert MET_FIELDS['shortwave_radiation'] == 'shortWaveRadiation'

    def test_swr_alias(self):
        assert MET_FIELDS['swr'] == 'shortWaveRadiation'

    def test_longwave_radiation(self):
        assert MET_FIELDS['longwave_radiation'] == 'longWaveRadiation'

    def test_lwr_alias(self):
        assert MET_FIELDS['lwr'] == 'longWaveRadiation'


class TestWaveMappings:
    def test_hm0(self):
        assert WAVE_FIELDS['hm0'] == 'waveHeight'

    def test_significant_wave_height(self):
        assert WAVE_FIELDS['significant_wave_height'] == 'waveHeight'

    def test_tp(self):
        assert WAVE_FIELDS['tp'] == 'wavePeriod'

    def test_wave_period(self):
        assert WAVE_FIELDS['wave_period'] == 'wavePeriod'

    def test_wave_direction(self):
        assert WAVE_FIELDS['wave_direction'] == 'waveDirection'

    def test_mwd(self):
        assert WAVE_FIELDS['mwd'] == 'waveDirection'

    def test_swell_height(self):
        assert WAVE_FIELDS['swell_height'] == 'swellHeight'

    def test_swell_period(self):
        assert WAVE_FIELDS['swell_period'] == 'swellPeriod'

    def test_swell_direction(self):
        assert WAVE_FIELDS['swell_direction'] == 'swellDirection'

    def test_wind_wave_height(self):
        assert WAVE_FIELDS['wind_wave_height'] == 'windWaveHeight'

    def test_wind_wave_period(self):
        assert WAVE_FIELDS['wind_wave_period'] == 'windWavePeriod'


class TestCurrentMappings:
    def test_current_speed(self):
        assert CURRENT_FIELDS['current_speed'] == 'currentSpeed'

    def test_current_direction(self):
        assert CURRENT_FIELDS['current_direction'] == 'currentDirection'


class TestOceanMappings:
    def test_sst(self):
        assert OCEAN_FIELDS['sst'] == 'sst'

    def test_conductivity(self):
        assert OCEAN_FIELDS['conductivity'] == 'conductivity'


# ──────────────────────────────────────────────────────────
# combine_series routing
# ──────────────────────────────────────────────────────────

class TestCombineSeriesRouting:

    def _single(self, parameter, value, unit):
        """Build series for one parameter/epoch and return the latest observation."""
        series = {parameter: ([(EPOCH, value)], unit, 'https://source')}
        rows = combine_series(STATION.id, series, STATION)
        assert len(rows) == 1
        return rows[0]

    def test_wave_height_routed_to_waves(self):
        obs = self._single('hm0', 2.1, 'm')
        assert obs.telemetry.waves['waveHeight'].value == 2.1
        assert obs.telemetry.waves['waveHeight'].unit == 'm'
        assert 'waveHeight' not in obs.telemetry.meteorology

    def test_wave_period_routed_to_waves(self):
        obs = self._single('tp', 8.5, 's')
        assert obs.telemetry.waves['wavePeriod'].value == 8.5

    def test_wave_direction_routed_to_waves(self):
        obs = self._single('wave_direction', 225.0, 'Deg')
        assert obs.telemetry.waves['waveDirection'].value == 225.0
        assert obs.telemetry.waves['waveDirection'].unit == '°'

    def test_swell_height_routed_to_waves(self):
        obs = self._single('swell_height', 1.5, 'm')
        assert obs.telemetry.waves['swellHeight'].value == 1.5

    def test_swell_period_routed_to_waves(self):
        obs = self._single('swell_period', 12.0, 's')
        assert obs.telemetry.waves['swellPeriod'].value == 12.0

    def test_swell_direction_routed_to_waves(self):
        obs = self._single('swell_direction', 180.0, 'deg')
        assert obs.telemetry.waves['swellDirection'].value == 180.0

    def test_wind_wave_height_routed_to_waves(self):
        obs = self._single('wind_wave_height', 0.8, 'm')
        assert obs.telemetry.waves['windWaveHeight'].value == 0.8

    def test_wind_wave_period_routed_to_waves(self):
        obs = self._single('wind_wave_period', 4.0, 's')
        assert obs.telemetry.waves['windWavePeriod'].value == 4.0

    def test_current_speed_routed_to_ocean(self):
        obs = self._single('current_speed', 0.45, 'm/s')
        assert obs.telemetry.ocean['currentSpeed'].value == 0.45

    def test_current_direction_routed_to_ocean(self):
        obs = self._single('current_direction', 135.0, 'Deg')
        assert obs.telemetry.ocean['currentDirection'].value == 135.0

    def test_sst_routed_to_ocean(self):
        obs = self._single('sst', 29.5, 'Deg C')
        assert obs.telemetry.ocean['sst'].value == 29.5
        assert obs.telemetry.ocean['sst'].unit == '°C'

    def test_conductivity_routed_to_ocean(self):
        obs = self._single('conductivity', 5.2, 'S/m')
        assert obs.telemetry.ocean['conductivity'].value == 5.2

    def test_shortwave_radiation_routed_to_meteorology(self):
        obs = self._single('shortwave_radiation', 350.0, 'W/m2')
        assert obs.telemetry.meteorology['shortWaveRadiation'].value == 350.0
        assert obs.telemetry.meteorology['shortWaveRadiation'].unit == 'W/m²'

    def test_longwave_radiation_routed_to_meteorology(self):
        obs = self._single('longwave_radiation', 400.0, 'W/m^2')
        assert obs.telemetry.meteorology['longWaveRadiation'].value == 400.0
        assert obs.telemetry.meteorology['longWaveRadiation'].unit == 'W/m²'

    def test_swr_alias_routed_to_meteorology(self):
        obs = self._single('swr', 280.0, 'w/m^2')
        assert obs.telemetry.meteorology['shortWaveRadiation'].value == 280.0

    def test_wind_gust_routed_to_meteorology(self):
        obs = self._single('wind_gust', 15.0, 'm/s')
        assert obs.telemetry.meteorology['windGust'].value == 15.0


class TestProfileRouting:

    def test_temperature_profile(self):
        series = {
            'water_temperature_1m': ([(EPOCH, 29.0)], 'Deg C', 'https://s'),
            'water_temperature_20m': ([(EPOCH, 27.5)], 'Deg C', 'https://s'),
            'water_temperature_100m': ([(EPOCH, 18.0)], 'Deg C', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        obs = rows[0]
        temps = obs.telemetry.profiles['temperature']
        assert len(temps) == 3
        assert temps[0].depth == 1
        assert temps[1].depth == 20
        assert temps[2].depth == 100
        assert obs.telemetry.ocean['sst'].value == 29.0

    def test_salinity_profile(self):
        series = {
            'salinity_1m': ([(EPOCH, 34.2)], 'PSU', 'https://s'),
            'salinity_50m': ([(EPOCH, 35.0)], 'PSU', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        obs = rows[0]
        sals = obs.telemetry.profiles['salinity']
        assert len(sals) == 2
        assert sals[0].depth == 1
        assert obs.telemetry.ocean['salinity'].value == 34.2

    def test_current_profile(self):
        series = {
            'current_speed_10m': ([(EPOCH, 0.3)], 'm/s', 'https://s'),
            'current_speed_50m': ([(EPOCH, 0.15)], 'm/s', 'https://s'),
            'current_direction_10m': ([(EPOCH, 90.0)], 'Deg', 'https://s'),
            'current_direction_50m': ([(EPOCH, 95.0)], 'Deg', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        obs = rows[0]
        currents = obs.telemetry.profiles['current']
        assert len(currents) == 4
        depths = sorted(set(p.depth for p in currents))
        assert depths == [10, 50]

    def test_surface_ocean_only_from_1m_depth(self):
        series = {
            'water_temperature_5m': ([(EPOCH, 28.0)], 'Deg C', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        assert 'sst' not in rows[0].telemetry.ocean


class TestMultiParameterObservation:
    """Verify a realistic multi-parameter observation combines correctly."""

    def test_full_observation_combines_all_groups(self):
        series = {
            'air_temperature': ([(EPOCH, 28.4)], 'Deg C', 'https://s'),
            'air_pressure': ([(EPOCH, 1013.0)], 'hPa', 'https://s'),
            'humidity': ([(EPOCH, 80.0)], '%', 'https://s'),
            'hm0': ([(EPOCH, 2.1)], 'm', 'https://s'),
            'tp': ([(EPOCH, 8.0)], 's', 'https://s'),
            'current_speed': ([(EPOCH, 0.5)], 'm/s', 'https://s'),
            'water_temperature_1m': ([(EPOCH, 29.5)], 'Deg C', 'https://s'),
            'salinity_1m': ([(EPOCH, 34.5)], 'PSU', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        assert len(rows) == 1
        obs = rows[0]
        assert obs.telemetry.meteorology['airTemperature'].value == 28.4
        assert obs.telemetry.meteorology['pressure'].value == 1013.0
        assert obs.telemetry.meteorology['humidity'].value == 80.0
        assert obs.telemetry.waves['waveHeight'].value == 2.1
        assert obs.telemetry.waves['wavePeriod'].value == 8.0
        assert obs.telemetry.ocean['currentSpeed'].value == 0.5
        assert obs.telemetry.ocean['sst'].value == 29.5
        assert obs.telemetry.ocean['salinity'].value == 34.5
        assert len(obs.telemetry.profiles['temperature']) == 1
        assert len(obs.telemetry.profiles['salinity']) == 1

    def test_missing_wave_params_leave_waves_empty(self):
        series = {
            'air_temperature': ([(EPOCH, 28.4)], 'Deg C', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        assert rows[0].telemetry.waves == {}

    def test_null_value_preserved(self):
        series = {
            'hm0': ([(EPOCH, None)], 'm', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        assert rows[0].telemetry.waves['waveHeight'].value is None

    def test_unrecognized_parameter_in_raw_payload_only(self):
        series = {
            'fabricated_param': ([(EPOCH, 42.0)], 'units', 'https://s'),
        }
        rows = combine_series(STATION.id, series, STATION)
        obs = rows[0]
        assert obs.telemetry.meteorology == {}
        assert obs.telemetry.ocean == {}
        assert obs.telemetry.waves == {}
        assert 'fabricated_param' in obs.rawPayload['parameters']
        assert obs.rawPayload['parameters']['fabricated_param']['value'] == 42.0


# ──────────────────────────────────────────────────────────
# Provider parameter discovery and availability tracking
# ──────────────────────────────────────────────────────────

class TestProviderParameterDiscovery:

    def _make_provider(self, option_list, series_data=None):
        """Return a provider with a mock transport that advertises the given options."""
        default_series = f"[[{EPOCH},28.0]]"
        data = series_data or default_series

        def respond(request):
            param = request.url.params.get('parameter', '')
            if param == '' and 'typeName' in str(request.url):
                return httpx.Response(200, json={'features': [
                    {'geometry': {'coordinates': [88.23, 6.57]},
                     'properties': {'Programme': 'OMNI', 'ID': 'BD14',
                                    'Reporting': 'Reporting', 'Agency': 'NIOT'}}
                ]})
            select = ''.join(f'<option value="{o}">{o}</option>' for o in option_list)
            html = (f'<select id="parameter">{select}</select>'
                    f"yAxis: [{{title: {{text: [\"Deg C\"]}}}}],"
                    f" series: [{{name: 'MB Data', data: {data}}}]")
            return httpx.Response(200, text=html)

        return IncoisBuoyProvider(httpx.AsyncClient(
            transport=httpx.MockTransport(respond)))

    @pytest.mark.asyncio
    async def test_discovers_all_offered_options(self):
        offered = ['air_temperature', 'air_pressure', 'hm0', 'tp',
                   'humidity', 'current_speed', 'swell_height']
        provider = self._make_provider(offered)
        provider.buoys = [STATION]
        provider.last_catalog = time.monotonic()
        try:
            await provider.get_latest_observation(STATION.id)
            avail = provider.parameter_status.get(STATION.id, {})
            for param in offered:
                assert avail.get(param) == 'AVAILABLE', f"{param} should be AVAILABLE"
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_not_offered_params_marked(self):
        offered = ['air_temperature', 'air_pressure']
        provider = self._make_provider(offered)
        provider.buoys = [STATION]
        provider.last_catalog = time.monotonic()
        try:
            await provider.get_latest_observation(STATION.id)
            avail = provider.parameter_status.get(STATION.id, {})
            assert avail.get('hm0') == 'NOT_OFFERED'
            assert avail.get('current_speed') == 'NOT_OFFERED'
            assert avail.get('swell_height') == 'NOT_OFFERED'
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_restricted_parameter_tracked(self):
        offered = ['air_temperature', 'wind_speed']

        def respond(request):
            param = request.url.params.get('parameter', '')
            if 'typeName' in str(request.url):
                return httpx.Response(200, json={'features': [
                    {'geometry': {'coordinates': [88.23, 6.57]},
                     'properties': {'Programme': 'OMNI', 'ID': 'BD14',
                                    'Reporting': 'Reporting', 'Agency': 'NIOT'}}
                ]})
            select = ''.join(f'<option value="{o}">{o}</option>' for o in offered)
            if param == 'wind_speed':
                return httpx.Response(200, text=f'<select>{select}</select>Data Download option is NOT available')
            html = (f'<select id="parameter">{select}</select>'
                    f"yAxis: [{{title: {{text: [\"Deg C\"]}}}}],"
                    f" series: [{{name: 'MB Data', data: [[{EPOCH},28.0]]}}]")
            return httpx.Response(200, text=html)

        provider = IncoisBuoyProvider(httpx.AsyncClient(
            transport=httpx.MockTransport(respond)))
        provider.buoys = [STATION]
        provider.last_catalog = time.monotonic()
        try:
            await provider.get_latest_observation(STATION.id)
            avail = provider.parameter_status.get(STATION.id, {})
            assert avail['wind_speed'] == 'RESTRICTED'
            assert 'wind_speed' not in provider.series.get(STATION.id, {})
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_core_parameters_fetched_every_cycle(self):
        """Core params (hm0, tp, current_speed, current_direction) are fetched
        every cycle, not deferred to hourly supplementary."""
        requests_seen = []
        offered = ['air_temperature', 'air_pressure', 'hm0', 'tp',
                   'current_speed', 'current_direction', 'humidity']

        def respond(request):
            param = request.url.params.get('parameter', '')
            if 'typeName' in str(request.url):
                return httpx.Response(200, json={'features': [
                    {'geometry': {'coordinates': [88.23, 6.57]},
                     'properties': {'Programme': 'OMNI', 'ID': 'BD14',
                                    'Reporting': 'Reporting', 'Agency': 'NIOT'}}
                ]})
            requests_seen.append(param)
            select = ''.join(f'<option value="{o}">{o}</option>' for o in offered)
            html = (f'<select id="parameter">{select}</select>'
                    f"yAxis: [{{title: {{text: [\"Deg C\"]}}}}],"
                    f" series: [{{name: 'MB Data', data: [[{EPOCH},28.0]]}}]")
            return httpx.Response(200, text=html)

        provider = IncoisBuoyProvider(httpx.AsyncClient(
            transport=httpx.MockTransport(respond)))
        provider.buoys = [STATION]
        provider.last_catalog = time.monotonic()
        try:
            # First call: fetches core + supplementary (hourly refresh)
            await provider.get_latest_observation(STATION.id)
            first_call_params = set(requests_seen)
            assert 'air_temperature' in first_call_params
            assert 'hm0' in first_call_params
            assert 'tp' in first_call_params
            assert 'current_speed' in first_call_params
            assert 'current_direction' in first_call_params
            # humidity is supplementary, also fetched on first call
            assert 'humidity' in first_call_params

            # Second call: within the hour, only core params re-fetched
            requests_seen.clear()
            await provider.get_latest_observation(STATION.id)
            second_call_params = set(requests_seen)
            assert 'air_temperature' in second_call_params
            assert 'hm0' in second_call_params
            assert 'tp' in second_call_params
            # humidity should NOT be re-fetched (supplementary, hourly only)
            assert 'humidity' not in second_call_params
        finally:
            await provider.close()

    @pytest.mark.asyncio
    async def test_wave_data_reaches_observation(self):
        offered = ['air_temperature', 'hm0', 'tp']

        call_count = {}
        def respond(request):
            param = request.url.params.get('parameter', '')
            if 'typeName' in str(request.url):
                return httpx.Response(200, json={'features': [
                    {'geometry': {'coordinates': [88.23, 6.57]},
                     'properties': {'Programme': 'OMNI', 'ID': 'BD14',
                                    'Reporting': 'Reporting', 'Agency': 'NIOT'}}
                ]})
            call_count[param] = call_count.get(param, 0) + 1
            select = ''.join(f'<option value="{o}">{o}</option>' for o in offered)
            if param == 'hm0':
                unit, val = 'm', '2.1'
            elif param == 'tp':
                unit, val = 's', '8.5'
            else:
                unit, val = 'Deg C', '28.4'
            html = (f'<select id="parameter">{select}</select>'
                    f"yAxis: [{{title: {{text: [\"{unit}\"]}}}}],"
                    f" series: [{{name: 'MB Data', data: [[{EPOCH},{val}]]}}]")
            return httpx.Response(200, text=html)

        provider = IncoisBuoyProvider(httpx.AsyncClient(
            transport=httpx.MockTransport(respond)))
        provider.buoys = [STATION]
        provider.last_catalog = time.monotonic()
        try:
            obs = await provider.get_latest_observation(STATION.id)
            assert obs is not None
            assert obs.telemetry.waves['waveHeight'].value == 2.1
            assert obs.telemetry.waves['waveHeight'].unit == 'm'
            assert obs.telemetry.waves['wavePeriod'].value == 8.5
            assert obs.telemetry.waves['wavePeriod'].unit == 's'
        finally:
            await provider.close()


# ──────────────────────────────────────────────────────────
# KNOWN_PARAMETERS and CORE_PARAMETERS sanity
# ──────────────────────────────────────────────────────────

def test_core_parameters_are_subset_of_known():
    assert CORE_PARAMETERS <= KNOWN_PARAMETERS


def test_known_parameters_cover_all_normalizer_keys():
    """Every key in WAVE_FIELDS, CURRENT_FIELDS, OCEAN_FIELDS should be in KNOWN_PARAMETERS
    (MET_FIELDS may include aliases like 'irradiance' that aren't INCOIS option names)."""
    for key in WAVE_FIELDS:
        assert key in KNOWN_PARAMETERS, f"WAVE_FIELDS key '{key}' not in KNOWN_PARAMETERS"
    for key in CURRENT_FIELDS:
        assert key in KNOWN_PARAMETERS, f"CURRENT_FIELDS key '{key}' not in KNOWN_PARAMETERS"
    for key in OCEAN_FIELDS:
        assert key in KNOWN_PARAMETERS, f"OCEAN_FIELDS key '{key}' not in KNOWN_PARAMETERS"
