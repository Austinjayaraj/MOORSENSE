# Official OON UTC provider — staged, not active

`services/buoy/incois_utc_provider.py` implements an isolated candidate using
`https://www.incois.gov.in/site/datainfo/moored_omnidata_stock.jsp` and exact source
option values. `BuoyRuntime` still constructs the original provider. No service
restart, database migration/history correction, Kafka publication, or production
outbox write is part of this validation.

The adapter requires `useUTC: true` and `Time (UTC)`, parses the embedded `MB Data`
JSON without executing JavaScript, and converts the actual Unix epoch directly
to an aware UTC datetime. It does not shift old timestamps. Original source
epochs, parameters, values, units, station IDs, URLs and response SHA256 remain
in `rawPayload.measurements`. `raw_source_timestamp` is the original numeric
epoch: the chart does not supply a separate timestamp string.

UTC observations have distinct observation, first-seen and receipt fields.
First-seen means this candidate instance first retrieved an epoch; it does not
mean that a physical observation arrived during the watch. It is currently
memory-only. Source publication time is explicitly null. Core retrieval checks
air temperature and pressure. Other actual options preserve their raw readings
when explicitly fetched; additional currents/waves/depth option mappings have
not been validated for the UI.

AD09, AD10 and BD12 are blocked before any measurement request. Previously
restricted wind options are also blocked. A restriction returned by the source
evicts the corresponding cached series and prevents another request during that
candidate instance. A public date-query index is metadata, not access permission.

Validation uses real public source responses plus reduced source-contract test
fixtures. The temporary arrival watcher imports no application, outbox, Kafka or
database modules. It records 16 BD14 reads on a 60-second schedule, spanning at
least 15 minutes between first and final response receipt. HTTP-body changes
alone do not count; a strictly newer source epoch is required.

Before activation, the requested source-arrival evidence must be reviewed. A
future integration must persist first-seen per event, retain null publication
time, distinguish initial source history from fresh arrival, and instrument the
same event ID through producer acknowledgment, SQL commit, WebSocket frame and
React render. Existing UI and persistence consumers run independently, so the
present implementation does not guarantee SQL commit before WebSocket delivery.
The existing WebSocket payload also omits event identity and these stage times.
Do not label a baseline's corrected UTC identity as a new physical arrival or
republish baseline history as live; plan explicit cutover behavior first.

Current age thresholds remain unchanged. Predominant three-hour sampling is
insufficient evidence of publication cadence or delivery grace. A numerical
LIVE rule requires fresh-arrival delivery measurements.

```sh
backend/.venv/bin/python -m pytest backend/tests/test_incois_utc_provider.py -q
```

Complete source captures, nine-station comparison and the finite watch log are
in the task's `utc-source-validation` evidence directory.
