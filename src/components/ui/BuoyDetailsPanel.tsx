import { useEffect, useState, useCallback } from 'react';
import { X } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { BuoyLocation, Metric } from '../../services/buoy/buoyTypes';
import { useBuoyTelemetry } from '../../services/buoy/useBuoyTelemetry';
import './BuoyDetailsPanel.css';

const labels: Record<string, string> = {
  windSpeed: 'Wind speed', windDirection: 'Wind direction', windGust: 'Wind gust',
  airTemperature: 'Air temperature', pressure: 'Pressure', humidity: 'Humidity',
  rainfall: 'Rainfall', radiation: 'Radiation',
  shortWaveRadiation: 'Shortwave radiation', longWaveRadiation: 'Longwave radiation',
  sst: 'Sea surface temperature', salinity: 'Salinity', conductivity: 'Conductivity',
  currentSpeed: 'Current speed', currentDirection: 'Current direction',
  waveHeight: 'Significant wave height', wavePeriod: 'Wave period', waveDirection: 'Wave direction',
  swellHeight: 'Swell height', swellPeriod: 'Swell period', swellDirection: 'Swell direction',
  windWaveHeight: 'Wind-wave height', windWavePeriod: 'Wind-wave period',
  temperature: 'Temperature', current: 'Current',
};

const metKeys = ['windSpeed', 'windDirection', 'windGust', 'airTemperature', 'pressure', 'humidity', 'rainfall', 'shortWaveRadiation', 'longWaveRadiation', 'radiation'] as const;
const waveKeys = ['waveHeight', 'wavePeriod', 'waveDirection', 'swellHeight', 'swellPeriod', 'swellDirection', 'windWaveHeight', 'windWavePeriod'] as const;
const currentKeys = ['currentSpeed', 'currentDirection'] as const;
const oceanKeys = ['sst', 'salinity', 'conductivity'] as const;

const dataAge = (seconds: number) => seconds < 60 ? `${Math.floor(seconds)} s` : seconds < 3600 ? `${Math.floor(seconds/60)} min` : seconds < 86400 ? `${Math.floor(seconds/3600)} h ${Math.floor(seconds%3600/60)} min` : `${Math.floor(seconds/86400)} d ${Math.floor(seconds%86400/3600)} h`;
const label = (key: string) => labels[key] ?? key.replace(/([A-Z])/g, ' $1');
const fmtValue = (metric: Metric) => `${metric.value?.toLocaleString(undefined, { maximumFractionDigits: 3 }) ?? '—'} ${metric.unit}`;

const paramAvailLabel: Record<string, string> = {
  AVAILABLE: '', RESTRICTED: 'RESTRICTED', NOT_OFFERED: 'NOT OFFERED',
  NO_DATA: 'NO DATA', SOURCE_UNAVAILABLE: 'SOURCE UNAVAILABLE', UNKNOWN: '',
};

// Reverse mapping: canonical telemetry key -> source parameter name for availability lookup
const canonToSource: Record<string, string> = {
  windSpeed: 'wind_speed', windDirection: 'wind_direction', windGust: 'wind_gust',
  airTemperature: 'air_temperature', pressure: 'air_pressure', humidity: 'humidity',
  rainfall: 'rainfall', radiation: 'irradiance',
  shortWaveRadiation: 'shortwave_radiation', longWaveRadiation: 'longwave_radiation',
  waveHeight: 'hm0', wavePeriod: 'tp', waveDirection: 'wave_direction',
  swellHeight: 'swell_height', swellPeriod: 'swell_period', swellDirection: 'swell_direction',
  windWaveHeight: 'wind_wave_height', windWavePeriod: 'wind_wave_period',
  currentSpeed: 'current_speed', currentDirection: 'current_direction',
  sst: 'sst', salinity: 'surface_salinity', conductivity: 'conductivity',
};

function ParameterGroup({ title, keys, group, metrics, paramAvail }: {
  title: string; keys: readonly string[]; group: string;
  metrics: Record<string, Metric>;
  paramAvail: Record<string, string>;
}) {
  const hasAny = keys.some(k => metrics[k]?.value !== null && metrics[k]?.value !== undefined);
  const hasRestricted = keys.some(k => {
    const src = canonToSource[k];
    return src && paramAvail[src] === 'RESTRICTED';
  });
  const allNotOffered = keys.every(k => {
    const src = canonToSource[k];
    return src && (paramAvail[src] === 'NOT_OFFERED' || paramAvail[src] === 'UNKNOWN');
  });

  if (allNotOffered && !hasAny) return null;

  return (
    <section>
      <h3>{title}</h3>
      <dl>
        {keys.map(key => {
          const metric = metrics[key];
          const src = canonToSource[key];
          const status = src ? paramAvail[src] : undefined;

          if (metric?.value !== null && metric?.value !== undefined) {
            return (
              <div key={key}>
                <dt>{label(key)}</dt>
                <dd>{fmtValue(metric)} <span className="buoy-type-badge">MEASURED</span></dd>
              </div>
            );
          }
          if (status === 'RESTRICTED') {
            return (
              <div key={key} className="buoy-dim">
                <dt>{label(key)}</dt>
                <dd><span className="buoy-restricted">RESTRICTED</span></dd>
              </div>
            );
          }
          if (status === 'NOT_OFFERED') return null;
          if (status === 'NO_DATA' || status === 'AVAILABLE') {
            return (
              <div key={key} className="buoy-dim">
                <dt>{label(key)}</dt>
                <dd><span className="buoy-nodata">NO DATA</span></dd>
              </div>
            );
          }
          return null;
        })}
      </dl>
      {hasRestricted && <p className="buoy-caption">INCOIS restricts downloads for marked parameters. No values are substituted.</p>}
    </section>
  );
}

function ProvenancedField({ label: lbl, value, unit, status, confidence }: {
  label: string; value: number | string | null | undefined; unit?: string;
  status?: string; confidence?: string;
}) {
  if (value !== null && value !== undefined) {
    const badge = status === 'AUTHORITATIVE' ? 'AUTHORITATIVE' :
      status === 'REFERENCE' ? 'REFERENCE' :
      status === 'INFERRED' ? 'INFERRED' :
      status === 'DERIVED' ? 'DERIVED · ESTIMATED' : status || '';
    return (
      <div><dt>{lbl}</dt><dd>
        {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : value}
        {unit ? ` ${unit}` : ''}
        {badge && <span className="buoy-derived"> {badge}</span>}
      </dd></div>
    );
  }
  return (
    <div className="buoy-dim"><dt>{lbl}</dt><dd>
      <span className="buoy-unavailable">{status === 'UNAVAILABLE' ? 'UNAVAILABLE' : status || 'UNAVAILABLE'}</span>
    </dd></div>
  );
}

function MooringSection({ buoyId }: { buoyId: string }) {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [response, setResponse] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    if (!buoyId) return;
    const controller = new AbortController();
    void fetch(`/api/buoys/${encodeURIComponent(buoyId)}/mooring/configuration`, { signal: controller.signal })
      .then(r => r.ok ? r.json() : null).then(setConfig).catch(() => {});
    void fetch(`/api/buoys/${encodeURIComponent(buoyId)}/mooring/response`, { signal: controller.signal })
      .then(r => r.ok ? r.json() : null).then(setResponse).catch(() => {});
    return () => controller.abort();
  }, [buoyId]);

  const pv = (obj: unknown): { value: number | null; unit: string; status: string; confidence: string } => {
    if (obj && typeof obj === 'object' && 'provenance' in obj) {
      const o = obj as Record<string, unknown>;
      const p = o.provenance as Record<string, string> | undefined;
      return { value: o.value as number | null, unit: (o.unit as string) || '', status: p?.status || '', confidence: p?.confidence || '' };
    }
    return { value: null, unit: '', status: 'UNAVAILABLE', confidence: '' };
  };

  const depth = config ? pv((config as Record<string, unknown>).water_depth) : null;
  const scope = config ? pv((config as Record<string, unknown>).scope) : null;
  const lineLen = config ? pv((config as Record<string, unknown>).total_line_length) : null;
  const lineCount = config ? pv((config as Record<string, unknown>).line_count) : null;
  const configStatus = config ? (config as Record<string, unknown>).configuration_status as string : 'LOADING';

  const tension = response?.fairlead_tension_n as number | null;
  const anchorT = response?.anchor_tension_n as number | null;
  const angle = response?.line_angle_deg as number | null;
  const util = response?.utilization as number | null;
  const sf = response?.safety_factor as number | null;
  const risk = response?.risk_state as string | null;
  const conf = response?.confidence as string | null;
  const solverStatus = response?.solver_status as string | null;

  return <>
    <section><h3>MOORING CONFIGURATION</h3>
      {configStatus && <p className="buoy-caption" style={{marginBottom: 10}}>
        Configuration: <strong>{configStatus}</strong> · {configStatus === 'AUTHORITATIVE' ? 'NIOT deployment records' : 'OMNI reference architecture + GEBCO bathymetry'}
      </p>}
      <dl>
        {depth && <ProvenancedField label="Water depth" value={depth.value} unit={depth.unit} status={depth.status} />}
        {scope && <ProvenancedField label="Mooring scope" value={scope.value} unit="" status={scope.status} />}
        {lineLen && <ProvenancedField label="Line length" value={lineLen.value} unit={lineLen.unit} status={lineLen.status} />}
        {lineCount && <ProvenancedField label="Line count" value={lineCount.value} unit="" status={lineCount.status} />}
        <ProvenancedField label="Mooring type" value={config ? 'INVERSE CATENARY' : null} status="REFERENCE" />
      </dl>
    </section>

    <section><h3>ESTIMATED MOORING RESPONSE</h3>
      {solverStatus === 'CONVERGED' || solverStatus === 'WARNING' ? <dl>
        <ProvenancedField label="Fairlead tension" value={tension ? Math.round(tension / 1000 * 100) / 100 : null} unit="kN" status="DERIVED" />
        <ProvenancedField label="Anchor tension" value={anchorT ? Math.round(anchorT / 1000 * 100) / 100 : null} unit="kN" status="DERIVED" />
        <ProvenancedField label="Line angle" value={angle} unit="°" status="DERIVED" />
        <ProvenancedField label="Utilization" value={util ? Math.round(util * 1000) / 10 : null} unit="%" status="DERIVED" />
        <ProvenancedField label="Safety factor" value={sf} unit="" status="DERIVED" />
        {risk && <div><dt>Risk state</dt><dd><span className={`buoy-risk-${risk.toLowerCase()}`}>{risk}</span></dd></div>}
        {conf && <div><dt>Confidence</dt><dd>{conf}</dd></div>}
      </dl> : <dl>
        <div className="buoy-dim"><dt>Solver</dt><dd><span className="buoy-unavailable">{solverStatus || 'NOT_RUN'}</span></dd></div>
      </dl>}
      <p className="buoy-caption">Tension is ESTIMATED (screening-level quasi-static catenary), not measured by a sensor.</p>
    </section>

    <section><h3>MODEL ASSUMPTIONS</h3>
      <ul className="buoy-assumptions">
        <li>OMNI inverse-catenary architecture (scope 1.22) used as reference</li>
        <li>Water depth from GEBCO bathymetry — actual deployment depth may differ</li>
        <li>Quasi-static analysis — no dynamic amplification or fatigue</li>
        <li>Screening-level Morison wave loading</li>
        <li>Reference material properties — not individual deployment specifications</li>
        <li>Pretension assumed as ~10% of reference net buoyancy (not deployment setting)</li>
        <li>Tension is estimated, not directly measured</li>
      </ul>
      <p className="buoy-caption" style={{marginTop: 8, lineHeight: 1.6}}>
        Mooring response is a screening-level quasi-static estimate. It is not a certified
        engineering analysis and does not replace authoritative NIOT deployment documentation,
        dynamic analysis, geotechnical analysis, or physical tension measurements.
      </p>
    </section>
  </>;
}

export function BuoyDetailsPanel({ buoy, onClose }: { buoy: BuoyLocation | null; onClose: () => void }) {
  const { detail, history, historyStatus, loading, error, websocketStatus } = useBuoyTelemetry(buoy);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 15000); return () => clearInterval(timer); }, []);
  useEffect(() => {
    if (!buoy) return;
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [buoy, onClose]);
  if (!buoy) return null;
  const metadata = detail?.id === buoy.id ? detail : buoy;
  const timestamp = detail?.observationTimestamp;
  const age = timestamp ? Math.max(0, (now - Date.parse(timestamp)) / 1000) : null;
  let freshness = detail?.freshness.state ?? 'OFFLINE';
  if ((error || detail?.freshness.sourceUnavailable) && timestamp && freshness !== 'OFFLINE') freshness = 'SOURCE_UNAVAILABLE';
  const unavailable = detail?.providerStatus === 'SOURCE_UNAVAILABLE';
  const telemetry = detail?.telemetry;
  const paramAvail = detail?.parameterAvailability ?? {};
  const trendKeys = [['meteorology','airTemperature'],['meteorology','windSpeed'],['ocean','sst'],['waves','waveHeight'],['meteorology','pressure']] as const;
  return <aside className="buoy-details" aria-label={`Details for ${buoy.id}`}>
    <header><div><span className="buoy-eyebrow">OBSERVATION STATION</span><h2>{metadata.name}</h2></div>
      <button onClick={onClose} aria-label="Close buoy details"><X size={18}/></button></header>
    <div className={`buoy-state state-${freshness.toLowerCase().replace('_', '-')}`}><i/>{!timestamp && (loading || detail?.providerStatus === 'CONNECTING') ? 'CONNECTING…' : unavailable ? 'SOURCE UNAVAILABLE' : !timestamp ? 'WAITING FOR DATA' : freshness.replace(/_/g, ' ')}</div>
    <p className="buoy-source">{detail?.source ?? 'NIOT / INCOIS'}{detail?.providerStatus ? ` · SOURCE ${detail.providerStatus.replace('SOURCE_', '').replace('_', ' ')}` : ''}</p>
    <p className="buoy-caption">LAST OBSERVATION · UTC<br/>{timestamp ? new Date(timestamp).toLocaleString('en-GB', {timeZone: 'UTC'}) : 'Not available'}</p>
    {loading && <div className="buoy-notice" role="status">Loading latest telemetry…</div>}
    {(error || detail?.error) && <div className="buoy-notice" role="alert"><strong>{timestamp ? 'SOURCE UNAVAILABLE · VALUES STALE' : 'SOURCE UNAVAILABLE'}</strong><span>Last known values are retained when available.</span></div>}

    <section><h3>POSITION</h3><dl>
      <div><dt>Latitude</dt><dd>{Math.abs(metadata.latitude).toFixed(6)}° {metadata.latitude < 0 ? 'S' : 'N'}</dd></div>
      <div><dt>Longitude</dt><dd>{Math.abs(metadata.longitude).toFixed(6)}° {metadata.longitude < 0 ? 'W' : 'E'}</dd></div>
      <div><dt>Deployment type</dt><dd>{metadata.type}</dd></div>
      <div><dt>Status</dt><dd>{metadata.status ?? 'UNKNOWN'}</dd></div>
      <div><dt>Data age</dt><dd>{age === null ? 'No observation' : dataAge(age)}</dd></div>
    </dl><p className="buoy-caption">INCOIS {metadata.coordinateKind} coordinates · retrieved {metadata.metadataRetrievedAt}. Current GPS position is unavailable.</p></section>

    {telemetry && <>
      <ParameterGroup title="METEOROLOGY" keys={metKeys} group="meteorology" metrics={telemetry.meteorology} paramAvail={paramAvail} />
      <ParameterGroup title="WAVES" keys={waveKeys} group="waves" metrics={telemetry.waves} paramAvail={paramAvail} />
      <ParameterGroup title="CURRENTS" keys={currentKeys} group="ocean" metrics={telemetry.ocean} paramAvail={paramAvail} />
      <ParameterGroup title="OCEAN CONDITIONS" keys={oceanKeys} group="ocean" metrics={telemetry.ocean} paramAvail={paramAvail} />

      {Object.entries(telemetry.profiles).filter(([, points]) => points.some(p => p.value !== null)).map(([key, points]) =>
        <section key={key}><h3>SUBSURFACE · {label(key)}</h3><dl>
          {points.filter(p => p.value !== null).map((point, index) =>
            <div key={index}><dt>{point.depth} {point.depthUnit} depth</dt><dd>{fmtValue(point)} <span className="buoy-type-badge">MEASURED</span></dd></div>)}
        </dl></section>)}
    </>}

    {!loading && !telemetry && <p className="buoy-caption">No source observations available. Measurements appear only when supplied by INCOIS.</p>}

    <MooringSection buoyId={buoy.id} />

    {timestamp && <section><h3>DATA PROVENANCE</h3><dl>
      <div><dt>Source</dt><dd>{detail?.source ?? 'INCOIS'}</dd></div>
      <div><dt>Observation (UTC)</dt><dd>{new Date(timestamp).toISOString()}</dd></div>
      <div><dt>Received</dt><dd>{detail?.receivedAt ? new Date(detail.receivedAt).toISOString() : 'N/A'}</dd></div>
      <div><dt>Age</dt><dd>{age !== null ? dataAge(age) : 'N/A'}</dd></div>
      <div><dt>Telemetry</dt><dd>MEASURED</dd></div>
      <div><dt>Data status</dt><dd>{freshness.replace(/_/g, ' ')}</dd></div>
    </dl></section>}
    {trendKeys.map(([group, key]) => {
      const data = history.map(o => ({ time: Date.parse(o.timestamp), value: o.telemetry[group]?.[key]?.value ?? null,
        unit: o.telemetry[group]?.[key]?.unit })).filter(o => o.value !== null);
      if (data.length < 2 || new Set(data.map(o => o.unit)).size !== 1) return null;
      return <section key={key}><h3>RECENT TREND · {label(key)} ({data[0].unit})</h3><div className="buoy-trend"><ResponsiveContainer width="100%" height={110}><LineChart data={data}>
        <XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={t => new Date(t).toLocaleTimeString('en-GB', {hour: '2-digit', minute: '2-digit', timeZone: 'UTC'})} tick={{fill: '#8297aa', fontSize: 9}}/>
        <YAxis width={35} domain={['auto', 'auto']} tick={{fill: '#8297aa', fontSize: 9}}/>
        <Tooltip labelFormatter={t => `${new Date(Number(t)).toISOString()} UTC`} contentStyle={{background: '#081421', border: '1px solid #204152', fontSize: 11}}/>
        <Line dataKey="value" stroke="#22d3ee" strokeWidth={1.5} dot={false} isAnimationActive={false}/>
      </LineChart></ResponsiveContainer></div></section>;
    })}
    {historyStatus === 'HISTORY UNAVAILABLE' && <p className="buoy-caption">Recent history unavailable.</p>}
    <footer><div><span>LAST OBSERVATION · UTC</span><strong>{timestamp ? new Date(timestamp).toLocaleString('en-GB', {timeZone: 'UTC'}) : 'Not available'}</strong></div>
      <div><span>STREAM</span><strong>{websocketStatus}</strong></div>
      {detail?.pipeline && <div><span>EVENT PIPELINE</span><strong>{detail.pipeline.kafka === 'CONNECTED' ? 'CONNECTED' : 'RECONNECTING'}</strong></div>}
    </footer>
  </aside>;
}
