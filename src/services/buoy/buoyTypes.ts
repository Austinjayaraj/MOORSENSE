export type BuoyStatus = 'SAFE' | 'WARNING' | 'CRITICAL' | 'ADRIFT' | 'OFFLINE' | 'UNKNOWN';
export interface Metric { value: number | null; unit: string }
export interface ProfilePoint extends Metric { depth: number; depthUnit: 'm' }
export interface Telemetry {
  meteorology: Record<string, Metric>;
  ocean: Record<string, Metric>;
  waves: Record<string, Metric>;
  profiles: Record<string, ProfilePoint[]>;
}
export interface BuoyLocation {
  id: string; name: string; type: string; latitude: number; longitude: number;
  status?: BuoyStatus; coordinateKind: string; metadataSource: string; metadataRetrievedAt?: string;
}
export interface BuoyDetail extends BuoyLocation {
  parameterAvailability?: Record<string, string>;
  observationTimestamp: string | null;
  receivedAt?: string | null;
  telemetry: Telemetry | null;
  source: string;
  providerStatus: string;
  error?: string | null;
  freshness: { state: string; ageSeconds: number | null; lastSourceCheck: string | null;
    sourceUnavailable: boolean; thresholds: { live: number; stale: number; offline: number };
    source_cadence_seconds?: number };
  pipeline?: { kafka: string; persistence: string };
}
export interface HistoryObservation { timestamp: string; telemetry: Telemetry }
