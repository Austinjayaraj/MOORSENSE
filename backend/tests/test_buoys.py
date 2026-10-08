"""Synthetic observations below are isolated test fixtures, never production data."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).parents[1]))
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from services.buoy.buoy_models import Observation
from services.buoy.buoy_cache import BuoyCache
from services.buoy.event_outbox import EventOutbox
from services.buoy.incois_provider import IncoisBuoyProvider
from services.buoy.base_provider import SourceAccessPending
from services.buoy.runtime import BuoyRuntime, BuoySettings
from workers.buoy_ingestion_worker import BuoyIngestionWorker
from app.api.routes_buoys import router


def observation(buoy='AD06', timestamp=None, identifier=None):
    return Observation(buoyId=buoy,timestamp=timestamp or datetime.now(timezone.utc)-timedelta(seconds=10),
        source='TEST_ONLY',observationId=identifier,
        telemetry={'meteorology': {'windSpeed': {'value': 0, 'unit':'m/s'},
                                  'humidity': {'value':None,'unit':'%'}},
                   'profiles': {'temperature':[{'depth':17.5,'value':21,'unit':'°C'}]}})


class FixtureProvider:
    def __init__(self, feed): self.feed=Path(feed); self.observations={}
    async def get_buoys(self):
        from services.buoy.buoy_models import Buoy
        return [Buoy(id=id,name=id,type='OMNI',latitude=0,longitude=0) for id in ('AD06','BD14')]
    async def refresh(self):
        rows=[Observation.model_validate(row) for row in json.loads(self.feed.read_text())['observations']]
        self.observations={id:[o for o in rows if o.buoyId==id] for id in ('AD06','BD14')}
    async def get_latest_observation(self,id):
        return max(self.observations.get(id,[]),key=lambda o:o.timestamp,default=None)

@pytest.mark.asyncio
async def test_public_provider_and_restrictions():
    import httpx
    from services.buoy.telemetry_normalizer import parse_chart
    seen=[]
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={'features':[{'geometry':{'coordinates':[67.45,18.495]},
            'properties':{'Programme':'OMNI','ID':'AD06','Reporting':'Reporting','Agency':'NIOT'}}]})
    provider=IncoisBuoyProvider(httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    stations=await provider.get_stations()
    assert len(stations)==1 and stations[0].id=='OMNI-AD06'
    assert stations[0].coordinateKind=='registry' and stations[0].latitude==18.495
    assert seen[0].url.params['typeName']=='JointPortal:Omni_Buoy'
    assert provider.diagnostics['providerReachable']
    assert parse_chart('Data Download option is NOT available')[3]=='RESTRICTED'
    with pytest.raises(ValueError): parse_chart('<html>Unexpected maintenance page</html>')
    await provider.close()

def test_chart_zero_null_exact_epochs_and_no_time_interpolation():
    from services.buoy.telemetry_normalizer import parse_chart,combine_series
    from services.buoy.buoy_models import Buoy
    html='yAxis: [{title: {text: ["Deg C"]}}, series: [{name: \'MB Data\', data: [[1780749000000,0],[1780759800000,null]]}]'
    points,unit,_,status=parse_chart(html)
    assert status=='AVAILABLE' and points[0][1]==0 and points[1][1] is None
    station=Buoy(id='OMNI-AD06',name='AD06',type='OMNI',latitude=18.495,longitude=67.45)
    rows=combine_series(station.id,{'air_temperature':(points,unit,'https://source'),
        'air_pressure':([(1780749000000,1007.5)],'hPa','https://source')},station)
    assert rows[-1].timestamp.isoformat()=='2026-06-06T15:30:00+00:00'
    assert 'pressure' not in rows[-1].telemetry.meteorology
    assert rows[0].telemetry.meteorology['airTemperature'].value==0


def test_missing_values_and_invalid_timestamps():
    obs = observation()
    assert obs.telemetry.meteorology['humidity'].value is None
    assert obs.telemetry.meteorology['windSpeed'].value == 0
    assert obs.telemetry.profiles['temperature'][0].depth == 17.5
    with pytest.raises(ValidationError): observation(timestamp=datetime(2020,1,1))
    with pytest.raises(ValidationError): observation(timestamp=datetime.now(timezone.utc)+timedelta(days=1))
    payload = obs.model_dump(mode='json')
    payload['telemetry']['ocean']={'sst': {'value':float('nan'),'unit':'°C'}}
    with pytest.raises(ValidationError): Observation.model_validate(payload)


def test_durable_dedup_and_monotonic_cache(tmp_path):
    path = tmp_path/'outbox.sqlite3'
    first = observation(timestamp=datetime.now(timezone.utc)-timedelta(hours=2))
    second = observation()
    box = EventOutbox(path)
    assert box.add(first)
    assert not box.add(first)
    assert box.add(second)
    key = box.pending()[0][0]
    box.acknowledge(key)
    box.close()
    box = EventOutbox(path)
    assert not box.add(first)
    assert len(box.pending()) == 1
    cache=BuoyCache()
    cache.update(second)
    cache.update(first)
    assert cache.latest['AD06'] == second
    box.close()


def test_freshness_and_source_failure():
    from services.buoy.buoy_models import Buoy
    buoy=Buoy(id='AD06',name='AD06',type='OMNI',latitude=18.2699,longitude=67.207667)
    cache=BuoyCache(60,120,240)
    cache.pending=False
    for age,state in [(10,'FRESH'),(90,'LATEST_AVAILABLE'),(180,'STALE'),(300,'OFFLINE')]:
        cache.latest.clear()
        cache.update(observation(timestamp=datetime.now(timezone.utc)-timedelta(seconds=age)))
        assert cache.detail(buoy)['freshness']['state'] == state
    cache.latest.clear()
    cache.update(observation())
    cache.checked('AD06','TELEMETRY UNAVAILABLE')
    detail=cache.detail(buoy)
    assert detail['freshness']['state']=='STALE'
    assert detail['telemetry']['meteorology']['windSpeed']['value']==0


@pytest.mark.asyncio
async def test_ingestion_dedup_and_failed_refresh_retains_cache(tmp_path):
    feed=tmp_path/'authorized.json'
    obs=observation()
    feed.write_text(json.dumps({'observations':[obs.model_dump(mode='json')]}))
    provider=FixtureProvider(feed)
    cache=BuoyCache()
    box=EventOutbox(tmp_path/'outbox.sqlite3')
    worker=BuoyIngestionWorker(provider,cache,box)
    await worker.poll_once()
    await worker.poll_once()
    assert len(box.pending())==1
    assert cache.latest['AD06'].timestamp == obs.timestamp
    feed.write_text('invalid')
    await worker.poll_once()
    assert cache.latest['AD06'].timestamp == obs.timestamp
    assert cache.errors['AD06']=='SOURCE UNAVAILABLE'
    box.close()


def test_rest_subscription_switch_close_and_reconnect(tmp_path):
    feed=tmp_path/"fixture.json"
    feed.write_text('{"observations":[]}')
    rt=BuoyRuntime(FixtureProvider(feed),config=BuoySettings(buoy_outbox_path=str(tmp_path/'outbox.sqlite3')))
    @asynccontextmanager
    async def lifespan(app):
        rt.buoys={b.id:b for b in await rt.provider.get_buoys()}
        for buoy in rt.buoys: rt.cache.checked(buoy,"SOURCE UNAVAILABLE")
        app.state.buoy_runtime=rt
        yield
    app=FastAPI(lifespan=lifespan)
    app.include_router(router)
    with TestClient(app) as client:
        assert len(client.get('/api/buoys').json())==2
        assert client.get('/api/buoys/debug/source').status_code==404
        rt.config.buoy_debug_source_enabled=True
        assert client.get('/api/buoys/debug/source').status_code==404
        rt.config.environment='development'
        assert client.get('/api/buoys/debug/source').json()['stations']==2
        assert client.get('/api/buoys/AD06').json()['telemetry'] is None
        assert client.get('/api/buoys/no-such-buoy').status_code==404
        assert client.get('/api/buoys/AD06/history?start=2020-01-01').status_code==422
        with client.websocket_connect('/ws/buoys') as ws:
            ws.send_json({'type':'subscribe','buoyId':'AD06'})
            assert ws.receive_json()['buoyId']=='AD06'
            ws.send_json({'type':'subscribe','buoyId':'BD14'})
            assert ws.receive_json()['buoyId']=='BD14'
            client.portal.call(rt.manager.broadcast,observation('AD06').event())
            client.portal.call(rt.manager.broadcast,observation('BD14').event())
            assert ws.receive_json()['buoyId']=='BD14'
            ws.send_json({'type':'unsubscribe'})
        assert not rt.manager.clients
        with client.websocket_connect('/ws/buoys') as ws:
            ws.send_json({'type':'subscribe','buoyId':'AD06'})
            assert ws.receive_json()['buoy']['providerStatus']=='SOURCE_UNAVAILABLE'
        with pytest.raises(Exception):
            with client.websocket_connect('/ws/buoys',headers={'origin':'https://untrusted.example'}) as ws:
                ws.receive_json()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get('BUOY_TEST_DATABASE_URL'),reason='Requires isolated test PostgreSQL + Kafka')
async def test_real_kafka_postgres_pipeline_on_isolated_topic(tmp_path,monkeypatch):
    # Fixtures stay on a unique TEST topic and in a separate TEST database.
    import services.buoy.runtime as runtime_module
    monkeypatch.setattr(runtime_module,'TOPIC',f'moorsense.telemetry.test.{uuid4()}')
    feed=tmp_path/'fixture.json'
    feed.write_text(json.dumps({'observations':[]}))
    provider=FixtureProvider(feed)
    rt=BuoyRuntime(provider,BuoySettings(buoy_outbox_path=str(tmp_path/'journal.sqlite3'),
        buoy_database_url=os.environ['BUOY_TEST_DATABASE_URL']))
    await rt.start()
    subscriber=object()
    rt.manager.add(subscriber)
    rt.manager.clients[subscriber]['buoyId']='AD06'
    obs=observation()
    feed.write_text(json.dumps({'observations':[obs.model_dump(mode='json')]}))
    worker=BuoyIngestionWorker(provider,rt.cache,rt.outbox)
    try:
        await worker.poll_once()
        event=await asyncio.wait_for(rt.manager.clients[subscriber]['queue'].get(),40)
        assert event['timestamp']==obs.timestamp.isoformat()
        assert event['telemetry']['meteorology']['windSpeed']['value']==0
        for _ in range(80):
            history=await rt.store.history('AD06',obs.timestamp-timedelta(seconds=1),obs.timestamp+timedelta(seconds=1),120)
            if history: break
            await asyncio.sleep(.25)
        assert len(history)==1
        assert history[0]['source']=='TEST_ONLY'
        await worker.poll_once()
        assert not rt.outbox.pending()
        assert rt.manager.clients[subscriber]['queue'].empty()
    finally:
        await rt.stop()


@pytest.mark.asyncio
async def test_kafka_outage_keeps_api_cache_and_pending_event(tmp_path):
    feed=tmp_path/'fixture.json'
    obs=observation()
    feed.write_text(json.dumps({'observations':[obs.model_dump(mode='json')]}))
    rt=BuoyRuntime(FixtureProvider(feed),BuoySettings(
        buoy_outbox_path=str(tmp_path/'outbox.sqlite3'),kafka_bootstrap_servers='127.0.0.1:1'))
    await rt.start()
    try:
        await asyncio.sleep(.2)
        assert rt.detail('AD06')['telemetry']['meteorology']['windSpeed']['value']==0
        assert len(rt.outbox.pending())==1
        assert rt.kafka_status=='RECONNECTING'
        assert all(not task.done() for task in rt.tasks)
    finally:
        await rt.stop()
