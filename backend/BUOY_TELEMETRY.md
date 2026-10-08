# Real INCOIS OMNI telemetry

The default provider retrieves actual INCOIS station metadata and observations. There is no mock/export file or static station fallback in the production buoy path. The public source currently supplies delayed observations: **source connected does not mean measurements are live**.

## Verified source requests — 8 October 2026

Browser Network inspection of https://www.incois.gov.in/jointportal/index.jsp, selecting only OMNI and opening AD06, discovered:

- Station GeoJSON: `https://www.incois.gov.in/geoserver/JointPortal/ows?service=WFS&version=1.0.0&request=GetFeature&typeName=JointPortal:Omni_Buoy&outputFormat=application/json` — HTTP 200, 12 OMNI features. Properties include ID, Programme, Agency, Reporting, and registry coordinates. The WFS response time is not an observation timestamp. These are **registry coordinates, not current GPS**.
- Chart document: `https://www.incois.gov.in/site/datainfo/moored_data_stock_download.jsp?buoy=AD06&parameter=air_temperature` — HTTP 200 HTML. It embeds the numeric JSON array for the `MB Data` series and an explicit y-axis unit. It does not issue an observation Fetch/XHR request. The public chart offers CSV/XLS export. The backend safely parses JSON, never executes page JavaScript, and rejects changed format, invalid values and future epochs.
- AD06 pressure: same observed chart endpoint with the form's `parameter=air_pressure`. Actual last array pairs: temperature `[1780759800000,30.326]`, pressure `[1780759800000,1006.02]`. The exact epoch gives **2026-06-06T15:30:00Z**, not today's date.
- The older `/portal/datainfo/` link in WFS properties returns a missing page. The current popup constructs `/site/datainfo/`. The earlier access-pending investigation used the old link; this adapter uses the functioning request observed in the current official popup.

Available parameter names come from the station's actual HTML select options. Profiles use depths encoded there, with no invented levels. Observations combine fields only when source epochs match. No interpolation, carry-forward across timestamps, or zero substitution occurs. Unknown units are preserved; explicit `Deg C`, `hPa`, `%`, `mm`, `psu`, and `w/m^2` units are normalized where applicable. Original units, URLs, per-parameter values and epoch are retained as provenance.

**Restrictions:** AD06 and other stations explicitly restrict wind downloads. These pages are classified RESTRICTED before parsing any data. Wind remains unavailable. EEZ stations AD09, AD10 and BD12 returned no usable public observations during this validation. Waves and currents are not offered in the discovered parameter lists; no guessed requests are made. A declared AVAILABLE parameter can still lack a reading at the latest epoch (for example 5 m temperature); it is omitted rather than substituted.

INCOIS's https://www.incois.gov.in/site/disclaimer.jsp allows public information access but states commercial reproduction requires permission from the competent authority. This local research validation does not establish commercial reproduction permission or an API service agreement. The HTML adapter depends on the public portal's format and availability.

## Run locally

```sh
docker compose -f compose.buoys.yaml up -d
cd backend
# Use the existing .venv, or install backend/requirements.txt in a virtualenv.
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

From the repository root in a second terminal:

```sh
MOORSENSE_BACKEND_URL=http://127.0.0.1:8001 npm run dev -- --host 127.0.0.1
```

Local Kafka uses port 9092; development PostgreSQL uses 15432. Production deployments should supply their own infrastructure credentials and origin allowlist. Forward both `/api` and `/ws/buoys` through the reverse proxy. Settings are in `.env.buoys.example`.

## Polling and delivery

One ingestion worker checks core air temperature/pressure every cycle, with `BUOY_POLL_INTERVAL_SECONDS=60` (minimum 60). A cycle's duration is added to the interval. Initial catalog and all discovered supplementary parameters are retrieved with a maximum of three source requests in flight. The station list and supplementary series refresh hourly because each public page returns a full multi-year array. Polling does not change the physical reporting cadence or make old data fresh.

At first retrieval, the last 120 genuine source epochs per station are caught up chronologically through the same pipeline. This is **historical catch-up**, never simulated real-time reporting. Later unseen station+timestamp pairs are journaled once in SQLite and published to `moorsense.telemetry` keyed by `OMNI-<station>`. Raw source epochs, location kind and URLs remain attached. PostgreSQL stores source/receipt timestamps, registry latitude/longitude, normalized measurements and the complete event. Database uniqueness plus durable outbox dedup prevents repeat storage/publication on unchanged polls. Delivery is at least once on send/ack crashes, with idempotent downstream storage.

Run one ingestion process per source and keep its SQLite journal persistent. API replicas set `BUOY_INGESTION_ENABLED=false`. Separate Kafka groups persist history and deliver selected station updates to the UI. UI consumers prevent old events replacing newer measurements. Restart restores cached observations from retained Kafka records. In-memory source failures retain last values and mark SOURCE_UNAVAILABLE/STALE; no readings are fabricated. The frontend maintains one WebSocket, switches subscriptions on selection, and advances data age locally. Metadata refreshes independently every 30 seconds without rebuilding globe state for telemetry events.

Freshness is computed only from source epochs and configured thresholds. SOURCE_UNAVAILABLE, source CONNECTED, WebSocket CONNECTED, and Kafka CONNECTED are separate states. Operational safety is UNKNOWN because the source's Reporting flag does not establish mooring integrity. Existing globe geometry, marker design, gestures and NOAA cloud implementation are preserved.

## Diagnostics

- `/api/health/buoys`: measured source reachability, last fetch and observation times, dynamic station count, persisted observations received in the last hour, Kafka/persistence connection state and WebSocket client count. `newObservationsLastHour` includes initial historical catch-up; it does not claim newly measured physical reports. A failed database count is null, not zero.
- `/api/buoys/debug/source`: source URLs, request/response timestamps, HTTP status, errors and parameter availability. It returns 404 unless **both** `ENVIRONMENT=development` and `BUOY_DEBUG_SOURCE_ENABLED=true` are set. No credentials are returned.
- `/api/buoys/{id}/history`: PostgreSQL history, by default anchored to the last source observation even when that observation is stale.

## Validation evidence

On 8 October 2026 the authoritative catalog returned **12** stations. Nine stations supplied usable public data. **1,080 genuine observations** (120 per usable station) traveled through INCOIS → parser → outbox → Kafka → PostgreSQL. The live browser subscribed to OMNI-BD14 before its initial source retrieval completed. Its panel changed from no observation to temperature **28.418°C**, pressure **1013.13 hPa**, humidity **79.738%**, SST **30.148°C**, timestamp **2026-10-07T18:30:00Z**, without a navigation/reload during arrival. The backend logged Kafka publication, WebSocket broadcast and PostgreSQL storage. The panel correctly marked STALE.

AD06 also displayed temperature **30.326°C**, pressure **1006.02 hPa**, humidity **77.297%**, SST **31.254°C**, source timestamp **2026-06-06T15:30:00Z**. All observations are older than the configured live threshold; no station is mislabeled LIVE. A newly published physical observation was not available during validation. Automatic detection of a future physical report remains dependent on INCOIS publishing it; the genuine historical catch-up demonstrates event delivery without inventing an arrival.

```sh
BUOY_TEST_DATABASE_URL=postgresql://moorsense:moorsense@localhost:15432/moorsense_test backend/.venv/bin/python -m pytest backend/tests/test_buoys.py -q
npm run build
```

Tests cover the observed WFS contract, strict chart parsing, download restrictions, exact epochs, nullable readings/zero preservation, no timestamp interpolation, profile depths, durable deduplication, monotonic cache, failure retention, WebSocket switching/origin checks, and real Kafka/PostgreSQL delivery. Synthetic fixtures run only on a unique TEST topic and a separate TEST database. They never enter the production telemetry topic. Physical hand tracking requires a camera session; that implementation was preserved.
