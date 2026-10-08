"""Adapter for requests observed in the official INCOIS OMNI portal.

The public chart embeds JSON arrays, not a REST telemetry API. No source script
is executed. Explicit download restrictions are honored before parsing data.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
import httpx
from .base_provider import BuoyDataProvider
from .buoy_models import Buoy
from .telemetry_normalizer import parse_chart, combine_series

log = logging.getLogger(__name__)
STATIONS_URL = 'https://www.incois.gov.in/geoserver/JointPortal/ows'
# UTC chart endpoint — epochs are genuine UTC, validated by useUTC: true contract.
# The older moored_data_stock_download.jsp uses IST-offset epochs (UTC+5:30)
# which caused a 5.5-hour display error. This endpoint is authoritative UTC.
CHART_URL = 'https://www.incois.gov.in/site/datainfo/moored_omnidata_stock.jsp'
STATION_PARAMS = dict(service='WFS', version='1.0.0', request='GetFeature',
                      typeName='JointPortal:Omni_Buoy', outputFormat='application/json')

# Parameters fetched every poll cycle (core environmental forcing inputs).
CORE_PARAMETERS = frozenset((
    'air_temperature', 'air_pressure',
    'hm0', 'tp',
    'current_speed', 'current_direction',
))

# All known INCOIS OMNI option values we should attempt when discovered.
# Not every buoy offers every parameter. The provider never guesses option
# names — it only fetches values that appear in the station's actual HTML
# <select> element.
KNOWN_PARAMETERS = frozenset((
    # Meteorology
    'air_temperature', 'air_pressure', 'humidity', 'rainfall',
    'wind_speed', 'wind_direction', 'wind_gust',
    'irradiance', 'shortwave_radiation', 'swr',
    'longwave_radiation', 'lwr',
    # Waves
    'hm0', 'significant_wave_height',
    'tp', 'wave_period', 'mean_wave_period',
    'wave_direction', 'mwd', 'mean_wave_direction',
    'swell_height', 'swell_period', 'swell_direction',
    'wind_wave_height', 'wind_wave_period',
    # Currents
    'current_speed', 'current_direction',
    # Ocean
    'sst', 'sea_surface_temperature', 'conductivity', 'surface_salinity',
))

class IncoisBuoyProvider(BuoyDataProvider):
    def __init__(self, client=None):
        self.client = client or httpx.AsyncClient(timeout=30, follow_redirects=True,
            headers={'User-Agent': 'MoorSense/1.0 public OMNI research viewer'})
        self.buoys = []
        self.observations = {}
        self.series = {}
        self.parameter_status = {}
        self.last_catalog = 0
        self.last_supplement = {}
        self.semaphore = asyncio.Semaphore(3)
        self.diagnostics = dict(provider='INCOIS', providerURL=CHART_URL,
            stationURL=STATIONS_URL, providerReachable=False, lastRequest=None,
            lastSuccessfulFetch=None, responseStatus=None, lastError=None)

    async def request(self, url, params):
        self.diagnostics['lastRequest'] = datetime.now(timezone.utc).isoformat()
        try:
            async with self.semaphore:
                response = await self.client.get(url, params=params)
            self.diagnostics['responseStatus'] = response.status_code
            response.raise_for_status()
            return response
        except Exception as exc:
            self.diagnostics.update(providerReachable=False, lastError=f'{type(exc).__name__}: source request failed')
            log.warning('[INCOIS] ERROR: %s', self.diagnostics['lastError'])
            raise

    def successful(self):
        self.diagnostics.update(providerReachable=True,
            lastSuccessfulFetch=datetime.now(timezone.utc).isoformat(), lastError=None)

    async def get_stations(self):
        if self.buoys and time.monotonic()-self.last_catalog < 3600:
            return self.buoys
        response = await self.request(STATIONS_URL, STATION_PARAMS)
        payload = response.json()
        stations = []
        for feature in payload['features']:
            p = feature['properties']
            if p['Programme'] != 'OMNI': continue
            lon, lat = feature['geometry']['coordinates'][:2]
            stations.append(Buoy(id=f"OMNI-{p['ID']}", name=f"OMNI-{p['ID']}", type='OMNI',
                latitude=lat, longitude=lon, coordinateKind='registry',
                metadataSource=STATIONS_URL, metadataRetrievedAt=datetime.now(timezone.utc).isoformat(),
                reportingStatus=p.get('Reporting'), agency=p.get('Agency')))
        if not stations: raise ValueError('INCOIS returned no OMNI stations')
        stations.sort(key=lambda b: (b.id != "OMNI-AD06", b.id))
        self.buoys = stations
        self.last_catalog = time.monotonic()
        self.successful()
        log.info('[INCOIS] Provider connection successful; retrieved %d OMNI stations', len(stations))
        return stations

    async def get_buoys(self): return await self.get_stations()

    async def get_station_metadata(self, buoy_id):
        return next((b for b in await self.get_stations() if b.id == buoy_id), None)

    async def refresh(self):
        await self.get_stations()

    async def fetch_parameter(self, buoy_id, parameter):
        response = await self.request(CHART_URL, {'buoy':buoy_id.removeprefix('OMNI-'), 'parameter':parameter})
        points, unit, options, status = parse_chart(response.text)
        self.parameter_status.setdefault(buoy_id,{})[parameter] = status
        self.successful()
        if status == 'AVAILABLE':
            self.series.setdefault(buoy_id,{})[parameter] = (points[-120:], unit, str(response.url))
        elif status == 'RESTRICTED':
            self.series.get(buoy_id, {}).pop(parameter, None)
        return options

    def _discovered_options(self, buoy_id):
        """Return the set of option values previously seen for this station."""
        return getattr(self, '_station_options', {}).get(buoy_id, set())

    async def get_latest_observation(self, buoy_id):
        # Phase 1: fetch air_temperature to discover the station's option list.
        options = await self.fetch_parameter(buoy_id, 'air_temperature')
        available_options = set(options) - {'999999'}
        if not hasattr(self, '_station_options'):
            self._station_options = {}
        self._station_options[buoy_id] = available_options

        # Mark parameters that this station simply does not offer.
        avail = self.parameter_status.setdefault(buoy_id, {})
        for known in KNOWN_PARAMETERS:
            if known not in available_options and known not in avail:
                avail[known] = 'NOT_OFFERED'

        # Phase 2: fetch core parameters every cycle (environmental forcing inputs).
        core_to_fetch = [p for p in CORE_PARAMETERS
                         if p != 'air_temperature' and p in available_options
                         and avail.get(p) != 'RESTRICTED']
        async def fetch_core(parameter):
            try:
                await self.fetch_parameter(buoy_id, parameter)
            except Exception:
                avail[parameter] = 'SOURCE_UNAVAILABLE'

        if core_to_fetch:
            await asyncio.gather(*(fetch_core(p) for p in core_to_fetch))

        # Phase 3: supplementary parameters refresh hourly (profiles, radiation, etc.).
        if time.monotonic() - self.last_supplement.get(buoy_id, 0) >= 3600:
            already = CORE_PARAMETERS | {'air_temperature'}
            supplement = [p for p in available_options
                          if p not in already and p != '999999'
                          and avail.get(p) != 'RESTRICTED']

            async def fetch_supplement(parameter):
                try:
                    await self.fetch_parameter(buoy_id, parameter)
                except Exception:
                    avail[parameter] = 'SOURCE_UNAVAILABLE'

            if supplement:
                await asyncio.gather(*(fetch_supplement(p) for p in supplement))
            self.last_supplement[buoy_id] = time.monotonic()

        station = next(b for b in self.buoys if b.id == buoy_id)
        observations = combine_series(buoy_id, self.series.get(buoy_id, {}), station)
        self.observations[buoy_id] = observations
        if not observations:
            return None
        latest = observations[-1]
        log.info('[INCOIS] %s observation: %s (%d params)',
                 buoy_id, latest.timestamp.isoformat(), len(self.series.get(buoy_id, {})))
        return latest

    async def get_history(self, buoy_id, start, end):
        return [o for o in self.observations.get(buoy_id,[]) if start <= o.timestamp <= end]

    async def close(self): await self.client.aclose()
