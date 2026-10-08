"""Staged official OON UTC adapter; intentionally not wired into BuoyRuntime.

Access restrictions established on the original portal apply to this endpoint
too. A new select option never grants access to a previously restricted field.
"""
import hashlib
import re
from datetime import datetime, timezone
from pydantic import field_validator, model_validator

from .buoy_models import Observation
from .incois_provider import IncoisBuoyProvider
from .telemetry_normalizer import combine_series, parse_chart

UTC_CHART_URL = 'https://www.incois.gov.in/site/datainfo/moored_omnidata_stock.jsp'
PUBLIC_STATIONS = frozenset(('AD06', 'AD07', 'AD08', 'BD08', 'BD09', 'BD10', 'BD11', 'BD13', 'BD14'))
RESTRICTED_STATIONS = frozenset(('AD09', 'AD10', 'BD12'))
RESTRICTED_PARAMETERS = frozenset(('wind_speed', 'wind_direction', 'wind_gust'))


def parse_utc_chart(html, parameter):
    points, unit, options, status = parse_chart(html)
    if status == 'RESTRICTED':
        return points, unit, options, status
    # Fail closed if the endpoint loses its explicit UTC contract. No timezone
    # arithmetic or browser-local interpretation is used anywhere in this adapter.
    if re.findall(r'useUTC\s*:\s*(true|false)\b', html) != ['true'] or 'Time (UTC)' not in html:
        raise ValueError('Official chart does not declare unambiguous UTC semantics')
    if parameter not in options or parameter == '999999':
        raise ValueError('Parameter is not an actual source option')
    return sorted(points, key=lambda point: point[0]), unit, options, status


class UtcObservation(Observation):
    firstSeenTimestamp: datetime
    sourcePublicationTimestamp: None = None

    @field_validator('firstSeenTimestamp')
    @classmethod
    def first_seen_has_timezone(cls, value):
        if value.tzinfo is None:
            raise ValueError('First-seen timestamp must include a timezone')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def first_seen_precedes_receipt(self):
        if self.receivedAt.tzinfo is None or self.firstSeenTimestamp > self.receivedAt:
            raise ValueError('Receipt must be timezone-aware and at or after first seen')
        return self

    def event(self):
        event = super().event()
        event.update(observation_timestamp=self.timestamp.isoformat(),
                     first_seen_timestamp=self.firstSeenTimestamp.isoformat(),
                     received_timestamp=self.receivedAt.isoformat(),
                     source_publication_timestamp=None)
        return event


class IncoisUtcBuoyProvider(IncoisBuoyProvider):
    """Candidate adapter. Memory-only first-seen is local retrieval, not publication.

    get_latest_observation fetches only the two already validated core fields.
    Other actual options can be explicitly fetched after access validation; their
    raw measurements remain preserved even when no UI metric mapping exists.
    Instantiating this provider does not create an outbox, Kafka client or SQL pool.
    """
    def __init__(self, client=None):
        super().__init__(client)
        self.options = {}
        self.evidence = {}
        self.first_seen = {}
        self.diagnostics.update(providerURL=UTC_CHART_URL, timestampSemantics='UTC',
                                implementationStatus='STAGED_NOT_ACTIVE')

    async def fetch_parameter(self, buoy_id, parameter):
        station_id = buoy_id.removeprefix('OMNI-')
        availability = self.parameter_status.setdefault(buoy_id, {})
        if station_id in RESTRICTED_STATIONS or parameter in RESTRICTED_PARAMETERS or availability.get(parameter) == 'RESTRICTED':
            availability[parameter] = 'RESTRICTED'
            self.series.get(buoy_id, {}).pop(parameter, None)
            return []
        if station_id not in PUBLIC_STATIONS:
            raise ValueError('Station has no verified public UTC measurement access')
        if parameter != 'air_temperature' and station_id not in self.options:
            await self.fetch_parameter(buoy_id, 'air_temperature')
        if station_id in self.options and parameter not in self.options[station_id]:
            raise ValueError('Parameter is not an actual source option')
        response = await self.request(UTC_CHART_URL, {'buoy': station_id, 'parameter': parameter})
        detected_at = datetime.now(timezone.utc)
        points, unit, options, status = parse_utc_chart(response.text, parameter)
        self.options[station_id] = set(options) - {'999999'}
        availability[parameter] = status
        self.successful()
        if status != 'AVAILABLE':
            self.series.get(buoy_id, {}).pop(parameter, None)
            self.evidence.get(buoy_id, {}).pop(parameter, None)
            return options
        points = points[-120:]
        self.series.setdefault(buoy_id, {})[parameter] = (points, unit, str(response.url))
        evidence = {}
        response_sha256 = hashlib.sha256(response.content).hexdigest()
        for epoch, value in points:
            timestamp = datetime.fromtimestamp(epoch / 1000, timezone.utc)
            first_seen = self.first_seen.setdefault((buoy_id, epoch), detected_at)
            evidence[epoch] = dict(raw_epoch_ms=epoch, raw_source_timestamp=epoch,
                raw_source_timestamp_encoding='Unix epoch milliseconds',
                observation_timestamp_utc=timestamp.isoformat(), parameter=parameter,
                value=value, unit=unit, buoy_id=buoy_id, source_station_id=station_id,
                source_url=str(response.url), first_seen_timestamp=first_seen.isoformat(),
                response_received_timestamp=detected_at.isoformat(),
                source_publication_timestamp=None,
                response_sha256=response_sha256)
        self.evidence.setdefault(buoy_id, {})[parameter] = evidence
        retained = {epoch for series, _, _ in self.series[buoy_id].values() for epoch, _ in series}
        self.first_seen = {key: value for key, value in self.first_seen.items()
                           if key[0] != buoy_id or key[1] in retained}
        return options

    async def get_latest_observation(self, buoy_id):
        if buoy_id.removeprefix('OMNI-') in RESTRICTED_STATIONS:
            self.parameter_status.setdefault(buoy_id, {})['air_temperature'] = 'RESTRICTED'
            return None
        await self.fetch_parameter(buoy_id, 'air_temperature')
        await self.fetch_parameter(buoy_id, 'air_pressure')
        station = await self.get_station_metadata(buoy_id)
        if station is None:
            raise ValueError('No official station metadata')
        rows = combine_series(buoy_id, self.series.get(buoy_id, {}), station)
        observations = []
        for row in rows:
            epoch = row.rawPayload['sourceEpochMs']
            raw = {**row.rawPayload, 'timestampSemantics': 'UTC',
                   'source_publication_timestamp': None,
                   'measurements': [evidence[epoch] for evidence in self.evidence.get(buoy_id, {}).values() if epoch in evidence]}
            observations.append(UtcObservation(**{**row.model_dump(), 'rawPayload': raw},
                                              firstSeenTimestamp=self.first_seen[(buoy_id, epoch)]))
        self.observations[buoy_id] = observations
        return observations[-1] if observations else None
