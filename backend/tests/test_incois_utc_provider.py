"""UTC source-contract tests. No Kafka, PostgreSQL or production outbox writes."""
import os
import sys
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from services.buoy.buoy_models import Buoy
from services.buoy.incois_utc_provider import IncoisUtcBuoyProvider, UtcObservation, parse_utc_chart, UTC_CHART_URL

# Real public BD14 pairs retrieved on 2026-10-08; reduced contract fixture.
HTML = '''<select id="parameter"><option value="air_temperature">Air Temperature</option>
<option value="air_pressure">Air Pressure</option><option value="hm0">Significant Wave Height</option></select>
global: {useUTC: true}, xAxis: {title: {text: 'Time (UTC)'}},
yAxis: [{title: {text: ["Deg C"]}}],
series: [{name: 'MB Data', data: [[1791417600000,28.418],[1791428400000,28.993]]}]'''


@pytest.mark.parametrize('timezone_name', ['UTC', 'Asia/Kolkata', 'America/Los_Angeles'])
def test_utc_epoch_independent_of_host_timezone(timezone_name):
    from datetime import datetime, timezone
    previous = os.environ.get('TZ')
    try:
        os.environ['TZ'] = timezone_name
        time.tzset()
        points, unit, _, status = parse_utc_chart(HTML, 'air_temperature')
        assert status == 'AVAILABLE' and unit == 'Deg C'
        assert points[-1] == (1791428400000, 28.993)
        assert datetime.fromtimestamp(points[-1][0]/1000, timezone.utc).isoformat() == '2026-10-08T03:00:00+00:00'
    finally:
        if previous is None: os.environ.pop('TZ', None)
        else: os.environ['TZ'] = previous
        time.tzset()


@pytest.mark.parametrize('html', [HTML.replace('useUTC: true', 'useUTC: false'),
                                HTML.replace('useUTC: true', ''), HTML.replace('Time (UTC)', 'Time')])
def test_ambiguous_timestamp_contract_rejected(html):
    with pytest.raises(ValueError, match='UTC|timestamp|ambiguous'):
        parse_utc_chart(html, 'air_temperature')


def test_access_precedes_measurement_parsing_and_options_are_exact():
    assert parse_utc_chart('Data Download option is NOT available', 'air_temperature')[3] == 'RESTRICTED'
    with pytest.raises(ValueError, match='actual source option'):
        parse_utc_chart(HTML, 'fabricated_parameter')


def test_timing_metadata_cannot_invent_publication_or_naive_first_seen():
    from datetime import datetime, timezone, timedelta
    from pydantic import ValidationError
    now = datetime.now(timezone.utc)
    payload = dict(buoyId='OMNI-BD14', timestamp=now-timedelta(hours=1),
                   receivedAt=now, firstSeenTimestamp=now, telemetry={})
    with pytest.raises(ValidationError, match='timezone'):
        UtcObservation(**{**payload, 'firstSeenTimestamp': now.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match='at or after'):
        UtcObservation(**{**payload, 'firstSeenTimestamp': now+timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        UtcObservation(**payload, sourcePublicationTimestamp=now)


@pytest.mark.asyncio
async def test_restricted_stations_wind_and_unknown_ids_make_no_requests():
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=HTML)
    provider = IncoisUtcBuoyProvider(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        for station in ('OMNI-AD09', 'OMNI-AD10', 'OMNI-BD12'):
            assert await provider.get_latest_observation(station) is None
            assert await provider.fetch_parameter(station, 'air_pressure') == []
            assert provider.parameter_status[station]['air_temperature'] == 'RESTRICTED'
        for parameter in ('wind_speed', 'wind_direction', 'wind_gust'):
            await provider.fetch_parameter('OMNI-BD14', parameter)
        with pytest.raises(ValueError, match='verified public'):
            await provider.fetch_parameter('OMNI-UNKNOWN', 'air_temperature')
        assert requests == []
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_raw_provenance_stable_identity_and_separate_receipt_times():
    requests = []
    def respond(request):
        requests.append(request)
        # Pressure uses the same real source epoch, but its own source unit/value.
        html = HTML if request.url.params['parameter'] == 'air_temperature' else HTML.replace('Deg C', 'hPa').replace('28.418', '1013.13').replace('28.993', '1015.09')
        return httpx.Response(200, text=html)
    provider = IncoisUtcBuoyProvider(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    provider.buoys = [Buoy(id='OMNI-BD14', name='BD14', type='OMNI', latitude=6.570556, longitude=88.233333)]
    provider.last_catalog = time.monotonic()
    try:
        first = await provider.get_latest_observation('OMNI-BD14')
        second = await provider.get_latest_observation('OMNI-BD14')
        assert first.identity == second.identity == 'OMNI-BD14:2026-10-08T03:00:00+00:00'
        assert first.firstSeenTimestamp == second.firstSeenTimestamp
        assert first.timestamp < first.firstSeenTimestamp <= first.receivedAt <= second.receivedAt
        event = second.event()
        assert event['source_publication_timestamp'] is None
        assert event['observation_timestamp'] == second.timestamp.isoformat()
        assert event['first_seen_timestamp'] == first.firstSeenTimestamp.isoformat()
        assert event['received_timestamp'] == second.receivedAt.isoformat()
        raw = event['rawPayload']['measurements'][0]
        assert raw['raw_epoch_ms'] == raw['raw_source_timestamp'] == 1791428400000
        assert raw['observation_timestamp_utc'] == '2026-10-08T03:00:00+00:00'
        assert raw['value'] == 28.993 and raw['unit'] == 'Deg C'
        assert raw['parameter'] == 'air_temperature' and raw['buoy_id'] == 'OMNI-BD14'
        assert raw['source_url'].startswith(UTC_CHART_URL)
        assert len(raw['response_sha256']) == 64
        assert all(str(request.url).startswith(UTC_CHART_URL) for request in requests)
        assert second.telemetry.meteorology['pressure'].value == 1015.09
        with pytest.raises(ValueError, match='actual source option'):
            await provider.fetch_parameter('OMNI-BD14', 'airTemperature')
        assert len(requests) == 4
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_new_restriction_evicts_cached_measurement_and_prevents_retry():
    count = 0
    def respond(request):
        nonlocal count
        count += 1
        return httpx.Response(200, text=HTML if count == 1 else 'Data Download option is NOT available')
    provider = IncoisUtcBuoyProvider(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        await provider.fetch_parameter('OMNI-BD14', 'air_temperature')
        assert provider.series['OMNI-BD14']['air_temperature']
        await provider.fetch_parameter('OMNI-BD14', 'air_temperature')
        await provider.fetch_parameter('OMNI-BD14', 'air_temperature')
        assert provider.parameter_status['OMNI-BD14']['air_temperature'] == 'RESTRICTED'
        assert 'air_temperature' not in provider.series['OMNI-BD14']
        assert count == 2
    finally:
        await provider.close()
