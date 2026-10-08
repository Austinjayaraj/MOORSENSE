import json
import math
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from .buoy_models import Observation

class Options(HTMLParser):
    def __init__(self): super().__init__(); self.values=[]
    def handle_starttag(self, tag, attrs):
        if tag == 'option':
            value=dict(attrs).get('value')
            if value: self.values.append(value)

def parse_chart(html):
    options=Options(); options.feed(html)
    if 'Data Download option is NOT available' in html:
        return [], None, options.values, 'RESTRICTED'
    # Validate UTC contract when the endpoint declares timestamp semantics.
    # The UTC endpoint includes useUTC: true and 'Time (UTC)' in the axis.
    # If useUTC is declared but false, or Time (UTC) is missing, fail closed
    # to prevent silent IST-to-UTC misinterpretation.
    utc_flags = re.findall(r'useUTC\s*:\s*(true|false)\b', html)
    if utc_flags and utc_flags != ['true']:
        raise ValueError('Source declares useUTC but not true — timestamp semantics ambiguous')
    if utc_flags and 'Time (UTC)' not in html:
        raise ValueError('Source declares useUTC: true but axis label missing Time (UTC)')
    # Bound extraction to the observed named series and the observed y-axis title.
    match=re.search(r"name\s*:\s*'MB Data'\s*,\s*data\s*:\s*(\[\[[\s\S]*?\]\]|\[\])",html)
    unit=re.search(r'yAxis\s*:[\s\S]*?title\s*:\s*\{\s*text\s*:\s*(\["[^"]*"\])',html)
    if not match or not unit: raise ValueError('INCOIS chart format changed or missing units')
    rows=json.loads(match.group(1)); source_unit=json.loads(unit.group(1))[0]
    points=[]
    for row in rows:
        if not isinstance(row,list) or len(row)!=2: raise ValueError('Invalid chart point')
        epoch,value=row
        if isinstance(epoch,bool) or not isinstance(epoch,(int,float)) or not math.isfinite(epoch):
            raise ValueError('Invalid source epoch')
        if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value)):
            raise ValueError('Invalid source value')
        if datetime.fromtimestamp(epoch/1000,timezone.utc)>datetime.now(timezone.utc):
            raise ValueError('Future source observation')
        points.append((epoch,value))
    return points,source_unit,options.values,'AVAILABLE' if points else 'NO_DATA'

MET_FIELDS = {
    'air_temperature': 'airTemperature',
    'air_pressure': 'pressure',
    'humidity': 'humidity',
    'rainfall': 'rainfall',
    'wind_speed': 'windSpeed',
    'wind_direction': 'windDirection',
    'wind_gust': 'windGust',
    'irradiance': 'radiation',
    'shortwave_radiation': 'shortWaveRadiation',
    'swr': 'shortWaveRadiation',
    'longwave_radiation': 'longWaveRadiation',
    'lwr': 'longWaveRadiation',
}

WAVE_FIELDS = {
    'hm0': 'waveHeight',
    'significant_wave_height': 'waveHeight',
    'tp': 'wavePeriod',
    'wave_period': 'wavePeriod',
    'mean_wave_period': 'wavePeriod',
    'wave_direction': 'waveDirection',
    'mwd': 'waveDirection',
    'mean_wave_direction': 'waveDirection',
    'swell_height': 'swellHeight',
    'swell_period': 'swellPeriod',
    'swell_direction': 'swellDirection',
    'wind_wave_height': 'windWaveHeight',
    'wind_wave_period': 'windWavePeriod',
}

CURRENT_FIELDS = {
    'current_speed': 'currentSpeed',
    'current_direction': 'currentDirection',
}

OCEAN_FIELDS = {
    'sst': 'sst',
    'sea_surface_temperature': 'sst',
    'conductivity': 'conductivity',
    'surface_salinity': 'salinity',
}

UNITS = {
    'Deg C': '°C', 'hPa': 'hPa', 'm/s': 'm/s', '%': '%', 'mm': 'mm',
    'Deg': '°', 'deg': '°',
    'PSU': 'PSU', 'psu': 'PSU', 'Psu': 'PSU',
    'W/m2': 'W/m²', 'W/m^2': 'W/m²', 'w/m^2': 'W/m²',
    'm': 'm', 's': 's', 'cm/s': 'cm/s', 'S/m': 'S/m',
}

# Canonical expected units per parameter. The INCOIS chart y-axis is sometimes
# unreliable (e.g. returning "cm/s" for temperature, "Deg C" for salinity).
# These take precedence over the chart y-axis for the canonical telemetry
# representation. The raw source unit is preserved in rawPayload for audit.
CANONICAL_PARAM_UNITS: dict[str, str] = {
    'air_temperature': '°C', 'air_pressure': 'hPa', 'humidity': '%',
    'rainfall': 'mm', 'wind_speed': 'm/s', 'wind_direction': '°',
    'wind_gust': 'm/s', 'irradiance': 'W/m²',
    'shortwave_radiation': 'W/m²', 'swr': 'W/m²',
    'longwave_radiation': 'W/m²', 'lwr': 'W/m²',
    'hm0': 'm', 'significant_wave_height': 'm',
    'tp': 's', 'wave_period': 's', 'mean_wave_period': 's',
    'wave_direction': '°', 'mwd': '°', 'mean_wave_direction': '°',
    'swell_height': 'm', 'swell_period': 's', 'swell_direction': '°',
    'wind_wave_height': 'm', 'wind_wave_period': 's',
    'current_speed': 'm/s', 'current_direction': '°',
    'sst': '°C', 'sea_surface_temperature': '°C',
    'conductivity': 'S/m', 'surface_salinity': 'PSU',
}

# Canonical units for profile parameter kinds, independent of chart y-axis.
_PROFILE_CANONICAL_UNITS: dict[str, str] = {
    'water_temperature': '°C',
    'salinity': 'PSU',
    'current_speed': 'm/s',
    'current_direction': '°',
}

# Profile patterns: parameter_depthm (e.g. water_temperature_20m, salinity_100m,
# current_speed_50m, current_direction_50m)
_PROFILE_RE = re.compile(
    r'^(water_temperature|salinity|current_speed|current_direction)_(\d+)m$'
)
_PROFILE_GROUP = {
    'water_temperature': 'temperature',
    'salinity': 'salinity',
    'current_speed': 'current',
    'current_direction': 'current',
}
_PROFILE_SURFACE_OCEAN = {
    'water_temperature': 'sst',
    'salinity': 'salinity',
}


def _resolve_unit(parameter, source_unit):
    """Return the canonical unit for a parameter.

    The INCOIS chart y-axis is unreliable for some parameters (e.g. reporting
    "cm/s" for a temperature field, "Deg C" for salinity). When a canonical
    unit is known for the parameter, use it. Otherwise normalize the source
    unit through the UNITS lookup. The raw source_unit is always preserved
    in rawPayload for audit.
    """
    if parameter in CANONICAL_PARAM_UNITS:
        return CANONICAL_PARAM_UNITS[parameter]
    m = _PROFILE_RE.fullmatch(parameter)
    if m and m.group(1) in _PROFILE_CANONICAL_UNITS:
        return _PROFILE_CANONICAL_UNITS[m.group(1)]
    return UNITS.get(source_unit, source_unit)


def combine_series(buoy_id, series, station):
    by_time = {}
    for parameter, (points, source_unit, url) in series.items():
        canonical_unit = _resolve_unit(parameter, source_unit)
        for epoch, value in points[-120:]:
            item = by_time.setdefault(epoch, dict(meteorology={}, ocean={}, waves={}, profiles={}))
            metric = {'value': value, 'unit': canonical_unit}

            if parameter in MET_FIELDS:
                item['meteorology'][MET_FIELDS[parameter]] = metric
            elif parameter in WAVE_FIELDS:
                item['waves'][WAVE_FIELDS[parameter]] = metric
            elif parameter in CURRENT_FIELDS:
                item['ocean'][CURRENT_FIELDS[parameter]] = metric
            elif parameter in OCEAN_FIELDS:
                item['ocean'][OCEAN_FIELDS[parameter]] = metric
            else:
                m = _PROFILE_RE.fullmatch(parameter)
                if m:
                    kind, depth_str = m.group(1), int(m.group(2))
                    group = _PROFILE_GROUP[kind]
                    item['profiles'].setdefault(group, []).append(
                        {**metric, 'depth': depth_str, 'depthUnit': 'm'})
                    if depth_str == 1 and kind in _PROFILE_SURFACE_OCEAN:
                        item['ocean'][_PROFILE_SURFACE_OCEAN[kind]] = metric
                # Parameters that match no mapping are preserved in rawPayload
                # but not routed into a telemetry group — they remain discoverable
                # without inventing a category.

    result = []
    for epoch, item in sorted(by_time.items())[-120:]:
        for points in item['profiles'].values():
            points.sort(key=lambda p: p['depth'])
        result.append(Observation(
            buoyId=buoy_id,
            timestamp=datetime.fromtimestamp(epoch / 1000, timezone.utc),
            telemetry=item,
            location={'latitude': station.latitude, 'longitude': station.longitude},
            rawPayload={
                'sourceEpochMs': epoch,
                'coordinateKind': 'registry',
                'parameters': {
                    p: {
                        'sourceURL': url,
                        'sourceUnit': unit,
                        'value': next((v for t, v in reversed(points) if t == epoch), None),
                    }
                    for p, (points, unit, url) in series.items()
                    if any(t == epoch for t, _ in points[-120:])
                },
            },
        ))
    return result

def normalize_observation(payload):
    observation=Observation.model_validate(payload)
    if not observation.rawPayload: observation.rawPayload=payload
    return observation
